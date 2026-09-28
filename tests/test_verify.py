"""Tests for app.verify.score_and_verify (rule-based, no network)."""

from app.models import Brand, EngineType, Evidence
from app.verify import score_and_verify

# NOTE: phone numbers below are synthetic test fixtures, not real numbers.
BRAND = Brand(
    id="hdfc-demo",
    display_name="HDFC Bank",
    official_domains=["hdfcbank.com"],
    official_phones=["+911800123456"],
    aliases=["HDFC"],
)


def _evidence(**overrides) -> Evidence:
    base = {
        "evidence_id": "ev1",
        "engine": EngineType.GOOGLE_SEARCH,
        "query": "HDFC Bank customer care number",
        "is_ad": False,
        "position": 2,
        "title": "HDFC Bank Customer Care",
        "link": "https://www.hdfcbank.com/contact",
        "snippet": "Call 1800 123 456 or visit hdfcbank.com",
        "raw": {},
    }
    base.update(overrides)
    return Evidence(**base)


def test_official_number_and_domain_not_flagged():
    result = score_and_verify(BRAND, [_evidence()])
    assert result.findings == []
    assert result.trust_score == 100


def test_unknown_number_in_ad_flagged_with_confidence_1():
    ev = _evidence(
        evidence_id="ev-ad",
        is_ad=True,
        position=None,
        snippet="Call now on 1800 999 888 for instant support",
    )
    result = score_and_verify(BRAND, [ev])
    phone_findings = [f for f in result.findings if f.kind.value == "unofficial_phone"]
    assert len(phone_findings) == 1
    assert phone_findings[0].value == "+911800999888"
    assert phone_findings[0].confidence == 1.0
    assert phone_findings[0].evidence_ids == ["ev-ad"]
    assert result.trust_score < 100


def test_typosquat_domain_caught_by_fuzzy_match():
    ev = _evidence(
        evidence_id="ev-typo",
        title="Customer Care Helpline",
        link="http://hdfcbank-support.com/contact",
        snippet="Reach our support team here",
    )
    result = score_and_verify(BRAND, [ev])
    domain_findings = [f for f in result.findings if "domain" in f.kind.value]
    assert len(domain_findings) == 1
    assert domain_findings[0].value == "hdfcbank-support.com"
    assert "resembles" in domain_findings[0].explanation


def test_findings_always_carry_evidence_ids():
    evs = [
        _evidence(evidence_id="ev-a", is_ad=True, snippet="Call 1800 999 888"),
        _evidence(
            evidence_id="ev-b",
            engine=EngineType.GOOGLE_MAPS,
            position=None,
            link="http://hdfcbank-support.com",
            snippet="Call 1800 999 888",
            raw={"unclaimed_listing": True},
        ),
    ]
    result = score_and_verify(BRAND, evs)
    assert result.findings, "expected findings for unofficial contact info"
    for finding in result.findings:
        assert finding.evidence_ids, "Finding must never have empty evidence_ids"


def test_unclaimed_maps_listing_boosts_confidence():
    claimed = _evidence(
        evidence_id="ev-c",
        engine=EngineType.GOOGLE_MAPS,
        position=None,
        snippet="Call 1800 999 888",
        raw={},
    )
    unclaimed = _evidence(
        evidence_id="ev-u",
        engine=EngineType.GOOGLE_MAPS,
        position=None,
        snippet="Call 1800 999 888",
        raw={"unclaimed_listing": True},
    )
    conf_claimed = score_and_verify(BRAND, [claimed]).findings[0].confidence
    conf_unclaimed = score_and_verify(BRAND, [unclaimed]).findings[0].confidence
    assert conf_unclaimed > conf_claimed
    assert conf_unclaimed <= 1.0


def test_empty_ads_transparency_is_normal():
    # No ads_transparency evidence at all: no findings, no trust penalty.
    result = score_and_verify(BRAND, [_evidence()])
    assert not any(e.engine == EngineType.ADS_TRANSPARENCY for e in result.evidence)
    assert result.findings == []
    assert result.trust_score == 100


def test_non_indian_phone_in_evidence_flagged_as_unofficial():
    # An evidence item with a non-Indian phone number should be flagged
    # as unofficial_phone since it won't match the Indian official_phones.
    ev = _evidence(
        evidence_id="ev-nonindian",
        is_ad=False,
        position=3,
        snippet="Call +44-800-555-0199 for support",
    )
    result = score_and_verify(BRAND, [ev])
    phone_findings = [f for f in result.findings if f.kind.value == "unofficial_phone"]
    assert len(phone_findings) == 1
    assert phone_findings[0].value == "+448005550199"
    assert result.trust_score < 100


def test_advertiser_mismatch_in_nested_item():
    # Ads Transparency item with a nested advertiser name that mismatches the brand.
    ev = _evidence(
        evidence_id="ev-ad-mismatch",
        engine=EngineType.ADS_TRANSPARENCY,
        query="HDFC Bank customer care number",
        is_ad=True,
        position=None,
        title="Some Other Bank",
        snippet="Call for support",
        raw={"advertiser": {"name": "Some Other Bank", "id": "otherbank"}},
    )
    result = score_and_verify(BRAND, [ev])
    adv_findings = [f for f in result.findings if f.kind.value == "advertiser_mismatch"]
    assert len(adv_findings) == 1
    assert adv_findings[0].value == "Some Other Bank"


def test_domain_unusual_subdomain_in_evidence():
    # A domain with an unusual subdomain that is not an exact match
    # should be flagged as unofficial_domain.
    ev = _evidence(
        evidence_id="ev-subdomain",
        title="Customer Care",
        link="http://hdfcbank-support.com/contact",
        snippet="Reach us here",
    )
    result = score_and_verify(BRAND, [ev])
    domain_findings = [f for f in result.findings if "domain" in f.kind.value]
    assert len(domain_findings) == 1
    assert domain_findings[0].value == "hdfcbank-support.com"
