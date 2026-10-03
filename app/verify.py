"""Rule-based verification and scoring.

Confidence rubric (simple and explainable, not sophisticated):
- 1.0: exact non-match phone shown in an ad (strongest signal — someone paid
  to display a number the brand does not own).
- 0.9: exact non-match phone in a maps/local listing; exact non-match domain
  in an ad (ad_off_domain).
- 0.8: exact non-match phone in a top-5 organic result; exact non-match
  domain in a maps/local listing.
- 0.75: advertiser name on an ad/Ads Transparency item matching neither the
  brand's display name nor any alias (advertiser_mismatch).
- 0.7: exact non-match domain in a top-5 organic result (unofficial_domain).
- 0.65: fuzzy near-miss domain (possible typosquat, rapidfuzz >= 85) in an
  ad or maps/local listing. Scaled DOWN vs an exact non-match because a
  similar-looking domain may still be a legitimate brand variant — similarity
  alone is weaker evidence than a wholly unrelated domain.
- 0.55: fuzzy near-miss domain in an organic-only mention (weakest signal).
- +0.15 boost (clamped to 1.0) on a maps_listing_mismatch whose raw evidence
  item has unclaimed_listing == True: an unclaimed listing showing unofficial
  contact info is a stronger impersonation signal than unofficial info alone.

False-positive guards (real testing showed generic platforms and unrelated
businesses dominating the findings):
- Neutral platforms (data/neutral_domains.json: marketplaces, social
  networks, email providers, directories, company-registry, news/wiki/video,
  review sites) never produce unofficial_domain or maps_listing_mismatch
  findings. They stay in the evidence list; they just are not flagged.
- Brand-relevance gate: a phone/domain from an organic result is flagged
  only when the result's title or snippet mentions the brand display_name or
  an alias (case-insensitive, spaces/punctuation ignored). A maps/local
  listing is flagged only when its title mentions the brand or an alias.
  Paid ads (is_ad or the Ads Transparency engine) always count.
- Dedupe: one Finding per (kind, value); evidence_ids are merged.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz

from app.extract import extract_advertiser_name, extract_domains, extract_phones
from app.models import Brand, EngineType, Evidence, Finding, FindingKind, ScanResult

FUZZY_THRESHOLD = 85
MAPS_UNCLAIMED_BOOST = 0.15
TOP_ORGANIC_CUTOFF = 5

# Severity weights for trust_score: trust_score = 100 - total_penalty,
# clamped to [0, 100]. Per-FINDING weights, most to least severe:
# - 25: ad-based mismatches (unofficial phone/domain in a paid ad) and fuzzy
#   lookalike domains in an ad or maps/listing — paid reach plus typosquat
#   intent is the strongest impersonation signal.
# - 20: exact maps/local listing mismatches (intercept "call now" traffic).
# - 15: advertiser-name mismatches, and fuzzy lookalike domains in organic
#   results (a near-miss domain is more suspicious than an unrelated one).
# - 10: unofficial phones in organic results.
# - 5:  exact unofficial domains in organic results — visible but competing
#   with official results, the weakest signal.
W_AD_MISMATCH = 25.0
W_MAPS_MISMATCH = 20.0
W_ADVERTISER_MISMATCH = 15.0
W_ORGANIC_FUZZY_DOMAIN = 15.0
W_ORGANIC_PHONE = 10.0
W_ORGANIC_DOMAIN = 5.0
# Per-KIND caps (chosen 2026-10-03 to keep worst-case score at >= 30/100):
# - AD_OFF_DOMAIN: 20
# - ADVERTISER_MISMATCH: 15
# - MAPS_LISTING_MISMATCH: 15
# - UNOFFICIAL_PHONE: 12
# - UNOFFICIAL_DOMAIN: 8
# Sum of all caps = 20 + 15 + 15 + 12 + 8 = 70, so a brand hitting every cap
# simultaneously still scores 100 - 70 = 30, never 0. Severity order kept:
# ad-based/advertiser (20/15) >= maps (15) >= fuzzy-domain/organic-phone
# (12, via UNOFFICIAL_PHONE) >= plain organic-domain (8). A large pile of
# same-kind organic mentions can no longer zero the score on its own, and
# even findings spanning every kind bottom out at 30, not 0.
MAX_PENALTY_BY_KIND: dict[FindingKind, float] = {
    FindingKind.AD_OFF_DOMAIN: 20.0,
    FindingKind.ADVERTISER_MISMATCH: 15.0,
    FindingKind.MAPS_LISTING_MISMATCH: 15.0,
    FindingKind.UNOFFICIAL_PHONE: 12.0,
    FindingKind.UNOFFICIAL_DOMAIN: 8.0,
}

_MAPS_ENGINES = {EngineType.GOOGLE_MAPS, EngineType.GOOGLE_LOCAL}

NEUTRAL_DOMAINS_PATH = Path(__file__).resolve().parent.parent / "data" / "neutral_domains.json"


def _load_neutral_domains() -> set[str]:
    """Well-known neutral platform domains that are never flagged.

    Missing/unreadable file -> empty set (fail open: flag everything, the
    pre-fix behaviour) rather than crashing a scan.
    """
    try:
        raw = json.loads(NEUTRAL_DOMAINS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(item).lower().strip() for item in raw if str(item).strip()}


NEUTRAL_DOMAINS: set[str] = _load_neutral_domains()


def _is_neutral(domain: str) -> bool:
    return domain.lower().strip() in NEUTRAL_DOMAINS


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalized(text: str | None) -> str:
    """Lowercase with spaces/punctuation stripped for brand-name matching."""
    return _NON_ALNUM_RE.sub("", (text or "").lower())


def _brand_tokens(brand: Brand) -> list[str]:
    """Normalized display_name + aliases; empties dropped (an empty token
    would substring-match every haystack)."""
    tokens: list[str] = []
    for name in [brand.display_name, *brand.aliases]:
        token = _normalized(name)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _mentions_brand(text: str | None, tokens: list[str]) -> bool:
    haystack = _normalized(text)
    return any(token in haystack for token in tokens)


def _is_prominent(evidence: Evidence) -> bool:
    """Whether a mention is visible enough to a customer to flag.

    Prominent = any ad, any maps/local listing, any Ads Transparency item,
    any top-5 organic position, or an organic item with unknown position
    (e.g. featured_snippet items carry no position — never silently drop
    them; real testing shows genuine numbers surface there).
    """
    if evidence.is_ad:
        return True
    if evidence.engine in _MAPS_ENGINES or evidence.engine == EngineType.ADS_TRANSPARENCY:
        return True
    if evidence.position is None:
        return True
    return evidence.position <= TOP_ORGANIC_CUTOFF


def _domain_similarity(candidate: str, official: str) -> float:
    """Best rapidfuzz partial_ratio between two domains.

    Compares both the full registrable domains and their second-level labels
    ("hdfcbank-support" vs "hdfcbank" -> 100): full-domain comparison alone
    scores a typosquat like "hdfcbank-support.com" vs "hdfcbank.com" at ~80,
    below the threshold, while the label comparison catches it.
    """
    candidate = candidate.lower().strip()
    official = official.lower().strip()
    full = fuzz.partial_ratio(candidate, official)
    cand_label = candidate.split(".")[0]
    off_label = official.split(".")[0]
    label = fuzz.partial_ratio(cand_label, off_label)
    return max(float(full), float(label))


def _best_official_domain_match(candidate: str, official_domains: list[str]) -> tuple[bool, bool, float]:
    """Return (is_exact, is_fuzzy_near_miss, best_score) for a domain."""
    best = 0.0
    for official in official_domains:
        if candidate.lower().strip() == official.lower().strip():
            return True, False, 100.0
        best = max(best, _domain_similarity(candidate, official))
    return False, best >= FUZZY_THRESHOLD, best


def _name_matches_brand(name: str, brand: Brand) -> bool:
    """True when an advertiser name matches the brand (exact or fuzzy)."""
    candidates = [brand.display_name, *brand.aliases]
    lowered = name.lower().strip()
    for candidate in candidates:
        official = candidate.lower().strip()
        if lowered == official:
            return True
        if fuzz.partial_ratio(lowered, official) >= FUZZY_THRESHOLD:
            return True
    return False


def _finding_id(brand_id: str, kind: FindingKind, value: str) -> str:
    digest = hashlib.sha1(f"{brand_id}:{kind.value}:{value}".encode()).hexdigest()[:16]
    return digest


def score_and_verify(brand: Brand, evidence: list[Evidence]) -> ScanResult:
    """Verify evidence against a brand's official info and score trust.

    Only prominent mentions (top-5 organic, any ad, any maps/local listing)
    can produce findings. An empty ads_transparency slice is normal (that
    engine returns empty for many real brands) — it yields no findings and
    costs no trust_score; only observed evidence ever creates a Finding.

    Brand-relevance gate: organic phones/domains count only when the
    title/snippet mentions the brand; maps/local items only when the listing
    title does; paid ads always count. Neutral platform domains never yield
    unofficial_domain or maps_listing_mismatch findings. Findings dedupe to
    one per (kind, value) with merged evidence_ids.
    """
    # (kind, value) -> {"evidence_ids": set, "confidence": max, "weight": max, "explanations": [...]}
    grouped: dict[tuple[FindingKind, str], dict] = {}

    def add_finding(kind: FindingKind, value: str, ev: Evidence, confidence: float, explanation: str, weight: float) -> None:
        key = (kind, value)
        slot = grouped.setdefault(
            key, {"evidence_ids": set(), "confidence": 0.0, "weight": 0.0, "explanations": []}
        )
        slot["evidence_ids"].add(ev.evidence_id)
        slot["confidence"] = max(slot["confidence"], min(1.0, confidence))
        slot["weight"] = max(slot["weight"], weight)
        slot["explanations"].append(explanation)

    official_phones = {p.strip() for p in brand.official_phones}
    tokens = _brand_tokens(brand)

    for ev in evidence:
        if not _is_prominent(ev):
            continue
        is_maps = ev.engine in _MAPS_ENGINES
        is_paid = ev.is_ad or ev.engine == EngineType.ADS_TRANSPARENCY
        organic_relevant = _mentions_brand(f"{ev.title or ''} {ev.snippet or ''}", tokens)
        maps_relevant = _mentions_brand(ev.title, tokens)
        haystack = " ".join(part for part in [ev.title, ev.snippet] if part)
        raw_json = json.dumps(ev.raw, default=str) if ev.raw else ""

        # --- phones: exact match only (fuzzy makes no sense for digits) ---
        for phone in extract_phones(f"{haystack} {raw_json}"):
            if phone in official_phones:
                continue
            if is_maps:
                if not maps_relevant:
                    continue
                confidence = 0.9
                if ev.raw.get("unclaimed_listing") is True:
                    confidence = min(1.0, confidence + MAPS_UNCLAIMED_BOOST)
                add_finding(
                    FindingKind.MAPS_LISTING_MISMATCH, phone, ev, confidence,
                    f"Maps/local listing shows phone {phone} not on the official list for {brand.display_name}.",
                    W_MAPS_MISMATCH,
                )
            elif is_paid:
                add_finding(
                    FindingKind.UNOFFICIAL_PHONE, phone, ev, 1.0,
                    f"Ad shows phone {phone} not on the official list for {brand.display_name}.",
                    W_AD_MISMATCH,
                )
            else:
                if not organic_relevant:
                    continue
                add_finding(
                    FindingKind.UNOFFICIAL_PHONE, phone, ev, 0.8,
                    f"Organic result shows phone {phone} not on the official list for {brand.display_name}.",
                    W_ORGANIC_PHONE,
                )

        # --- domains: exact match first, then fuzzy near-miss ---
        domain_candidates: list[str] = []
        for source in [ev.link or "", ev.title or "", ev.snippet or ""]:
            domain = extract_domains(source)
            if domain and domain not in domain_candidates:
                domain_candidates.append(domain)
        for raw_key in ("website", "displayed_link", "domain", "site"):
            raw_value = ev.raw.get(raw_key)
            if isinstance(raw_value, str) and raw_value.strip():
                domain = extract_domains(raw_value)
                if domain and domain not in domain_candidates:
                    domain_candidates.append(domain)

        for domain in domain_candidates:
            is_exact, is_fuzzy, score = _best_official_domain_match(domain, brand.official_domains)
            if is_exact:
                continue
            tag = f" (resembles official domain, similarity {score:.0f})" if is_fuzzy else ""
            if is_paid:
                # Ads always count, even for neutral platforms: a paid ad is
                # an explicit endorsement regardless of where it points.
                confidence = 0.65 if is_fuzzy else 0.9
                add_finding(
                    FindingKind.AD_OFF_DOMAIN, domain, ev, confidence,
                    f"Ad links to {domain}, not on the official domain list for {brand.display_name}{tag}.",
                    W_AD_MISMATCH,
                )
            elif is_maps:
                if _is_neutral(domain) or not maps_relevant:
                    continue
                confidence = 0.65 if is_fuzzy else 0.8
                if ev.raw.get("unclaimed_listing") is True:
                    confidence = min(1.0, confidence + MAPS_UNCLAIMED_BOOST)
                add_finding(
                    FindingKind.MAPS_LISTING_MISMATCH, domain, ev, confidence,
                    f"Maps/local listing links to {domain}, not on the official domain list for {brand.display_name}{tag}.",
                    W_AD_MISMATCH if is_fuzzy else W_MAPS_MISMATCH,
                )
            else:
                if _is_neutral(domain) or not organic_relevant:
                    continue
                confidence = 0.55 if is_fuzzy else 0.7
                add_finding(
                    FindingKind.UNOFFICIAL_DOMAIN, domain, ev, confidence,
                    f"Organic result links to {domain}, not on the official domain list for {brand.display_name}{tag}.",
                    W_ORGANIC_FUZZY_DOMAIN if is_fuzzy else W_ORGANIC_DOMAIN,
                )

        # --- advertiser name: only when the item actually names one ---
        if is_paid:
            advertiser = extract_advertiser_name(ev.raw)
            if advertiser and not _name_matches_brand(advertiser, brand):
                add_finding(
                    FindingKind.ADVERTISER_MISMATCH, advertiser, ev, 0.75,
                    f"Ad/Ads Transparency item names advertiser '{advertiser}', matching neither "
                    f"{brand.display_name} nor its aliases.",
                    W_ADVERTISER_MISMATCH,
                )

    findings: list[Finding] = []
    for (kind, value), slot in sorted(grouped.items(), key=lambda item: (item[0][0].value, item[0][1])):
        findings.append(
            Finding(
                finding_id=_finding_id(brand.id, kind, value),
                kind=kind,
                value=value,
                evidence_ids=sorted(slot["evidence_ids"]),
                confidence=round(slot["confidence"], 2),
                explanation=" ".join(dict.fromkeys(slot["explanations"])),
            )
        )

    # Hard invariant: a Finding must always trace back to stored evidence.
    # (Finding.evidence_ids also enforces min_length=1 at the model level.)
    assert all(f.evidence_ids for f in findings), "Finding created without evidence_ids"

    penalty_by_kind: dict[FindingKind, float] = {}
    for finding in findings:
        key = (finding.kind, finding.value)
        subtotal = penalty_by_kind.get(finding.kind, 0.0) + grouped[key]["weight"]
        penalty_by_kind[finding.kind] = subtotal
    penalty = sum(
        min(subtotal, MAX_PENALTY_BY_KIND[kind]) for kind, subtotal in penalty_by_kind.items()
    )
    trust_score = max(0, min(100, round(100 - penalty)))

    return ScanResult(
        brand_id=brand.id,
        scanned_at=datetime.now(timezone.utc),
        trust_score=trust_score,
        findings=findings,
        evidence=list(evidence),
    )
