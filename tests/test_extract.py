"""Tests for app.extract (pure functions, no network)."""

from app.extract import extract_advertiser_name, extract_domains, extract_phones


def test_extract_phones_normalizes_indian_number():
    # NOTE: all numbers below are synthetic test fixtures, not real numbers.
    assert extract_phones("Call us on 1800 123 456 today") == ["+911800123456"]


def test_extract_phones_dedupes_repeated_number():
    numbers = extract_phones("Call 1800 123 456 or 1800-123-456 again")
    assert numbers == ["+911800123456"]


def test_extract_phones_empty_text():
    assert extract_phones("no numbers here, just HDFC Bank support") == []
    assert extract_phones("") == []


def test_extract_domains_from_url():
    assert extract_domains("https://support.hdfcbank.com/contact-us?x=1") == "hdfcbank.com"


def test_extract_domains_from_raw_text():
    assert extract_domains("Visit hdfcbank-support.com now for help") == "hdfcbank-support.com"


def test_extract_domains_none_when_absent():
    assert extract_domains("Call HDFC Bank support") is None
    assert extract_domains("") is None


def test_extract_advertiser_name_known_key():
    assert extract_advertiser_name({"advertiser_name": "Acme Support Services"}) == "Acme Support Services"


def test_extract_advertiser_name_missing():
    assert extract_advertiser_name({}) is None
    assert extract_advertiser_name({"unrelated_field": "x"}) is None


def test_extract_phones_non_indian_format():
    # Numbers not in Indian format should be ignored (region="IN").
    # US format with country code +1 and space does not match Indian region.
    assert extract_phones("Call +1 555 0199 today") == []
    # Very short number with parens does not match.
    assert extract_phones("Call (555) 123-4567 today") == []


def test_extract_domains_unusual_subdomain():
    # A domain with an unusual multi-level subdomain: tldextract correctly
    # resolves the registrable domain underneath the subdomain.
    assert extract_domains("Visit sub.domain.example.co.uk now") == "example.co.uk"
    assert extract_domains("http://nested.sub.stack.io/page") == "stack.io"


def test_extract_advertiser_name_malformed_item():
    # Item missing all known advertiser name keys returns None
    assert extract_advertiser_name({"some_other_field": "x"}) is None
    # Item with only nested advertiser key that is empty dict
    assert extract_advertiser_name({"advertiser": {}}) is None
    # Item with nested advertiser dict that has a name key (in _NESTED_ADVERTISER_KEYS)
    assert (
        extract_advertiser_name({"advertiser": {"name": "Acme"}})
        == "Acme"
    )
