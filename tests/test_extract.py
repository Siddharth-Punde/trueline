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
