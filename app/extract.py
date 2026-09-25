"""Pure extraction helpers: phones, domains, advertiser names.

No network calls. All functions are deterministic and side-effect free.
"""

from __future__ import annotations

import re
from typing import Any

import phonenumbers
import tldextract

# Matches a URL or bare hostname inside free text. The registrable domain is
# then resolved with tldextract (which alone cannot find a host inside a
# sentence — verified: tldextract.extract("Visit hdfcbank-support.com now")
# returns an empty domain, so this pre-scan is required).
_URL_OR_HOST_RE = re.compile(
    r"(?:https?://)?(?:www\.)?([A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,})(?::\d+)?(?:/[^\s]*)?"
)


def extract_phones(text: str) -> list[str]:
    """Find Indian phone numbers in text and normalize them to E.164.

    Uses phonenumbers.PhoneNumberMatcher with region "IN"; keeps only
    possible numbers; returns unique values in order of first appearance.
    """
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in phonenumbers.PhoneNumberMatcher(text, "IN"):
        number = match.number
        if not phonenumbers.is_possible_number(number):
            continue
        e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        if e164 not in seen:
            seen.add(e164)
            found.append(e164)
    return found


def _registered_domain(candidate: str) -> str | None:
    ext = tldextract.extract(candidate)
    # top_domain_under_public_suffix == domain + suffix ("example.co.uk").
    registered = getattr(ext, "top_domain_under_public_suffix", "") or ""
    if registered:
        return registered.lower()
    return None


def extract_domains(text_or_url: str) -> str | None:
    """Pull the registrable domain (e.g. "hdfcbank.com") from a URL or text.

    Scans for the first URL/host-like token, then resolves it with
    tldextract. Returns None when no registrable domain is present.
    """
    if not text_or_url:
        return None
    for match in _URL_OR_HOST_RE.finditer(text_or_url):
        registered = _registered_domain(match.group(0))
        if registered:
            return registered
    return None


# VERIFY-ME (maintainer): these key names are GUESSES for the advertiser's
# legal/display name field in a real SerpApi Ads Transparency API response
# item. I had no real fixture to check against. Please run one live
# Ads Transparency lookup (or open a saved raw fixture) and keep only the
# key(s) that actually exist — then delete this comment.
_ADVERTISER_NAME_KEYS: tuple[str, ...] = (
    "advertiser_name",
    "advertiser_legal_name",
    "advertiser_display_name",
    "advertiser_verified_name",
    "advertiser",
    "advertiser_company_name",
    "company_name",
    "name",
)

_NESTED_ADVERTISER_KEYS: tuple[str, ...] = (
    "legal_name",
    "display_name",
    "verified_name",
    "company_name",
    "name",
)


def extract_advertiser_name(ads_transparency_item: dict[str, Any]) -> str | None:
    """Pull the advertiser's legal/display name from an Ads Transparency item.

    Returns None when the item carries no recognizable name field.
    See the VERIFY-ME comment above about the exact field name.
    """
    if not isinstance(ads_transparency_item, dict):
        return None
    for key in _ADVERTISER_NAME_KEYS:
        value = ads_transparency_item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = ads_transparency_item.get("advertiser")
    if isinstance(nested, dict):
        for key in _NESTED_ADVERTISER_KEYS:
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
