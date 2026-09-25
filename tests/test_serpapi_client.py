import json

import pytest

from app.serpapi_client import (
    FixtureMissingError,
    SerpApiClient,
    build_cache_key,
    resolve_engine,
)


def test_cache_key_stable_regardless_of_dict_order():
    params_a = {"q": "acme customer care", "gl": "in", "hl": "en", "ll": "@20,78,4z"}
    params_b = {"ll": "@20,78,4z", "hl": "en", "gl": "in", "q": "acme customer care"}

    key = build_cache_key("google", params_a)
    assert key == build_cache_key("google", params_b)
    assert len(key) == 64 and set(key) <= set("0123456789abcdef")


def test_cache_key_changes_with_values_and_nested_key_order():
    base = {"q": "acme", "filter": {"a": 1, "b": 2}}
    same_nested = {"filter": {"b": 2, "a": 1}, "q": "acme"}
    assert build_cache_key("google", base) == build_cache_key("google", same_nested)

    assert build_cache_key("google", base) != build_cache_key("google", {"q": "acme", "filter": {"a": 1, "b": 3}})
    assert build_cache_key("google", base) != build_cache_key("google_maps", base)


def test_engine_aliases_share_the_same_fixture():
    params = {"q": "acme", "region": "2356"}
    assert resolve_engine("google_ads_transparency") == "google_ads_transparency_center"
    assert build_cache_key("google_ads_transparency", params) == build_cache_key(
        "google_ads_transparency_center", params
    )
    assert build_cache_key("google_search", {"q": "x"}) == build_cache_key("google", {"q": "x"})


def test_replay_mode_raises_fixture_missing_error(tmp_path):
    client = SerpApiClient(mode="replay", fixtures_dir=tmp_path, api_key="")
    params = {"q": "acme customer care", "gl": "in", "hl": "en"}
    expected = tmp_path / f"{build_cache_key('google', params)}.json"

    with pytest.raises(FixtureMissingError) as exc_info:
        client.search("google", params)

    assert str(expected) in str(exc_info.value)
    assert expected.name in str(exc_info.value)
    assert exc_info.value.fixture_path == expected
    assert not expected.exists()


def test_replay_mode_returns_saved_fixture(tmp_path):
    params = {"gl": "in", "hl": "en", "q": "acme refund"}
    payload = {"organic_results": [{"position": 1, "title": "Acme"}]}
    (tmp_path / f"{build_cache_key('google', params)}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    client = SerpApiClient(mode="replay", fixtures_dir=tmp_path, api_key="")
    shuffled = {"q": "acme refund", "hl": "en", "gl": "in"}

    assert client.search("google", shuffled) == payload


def test_live_mode_writes_fixture_before_returning(tmp_path, monkeypatch):
    payload = {"search_information": {"query_displayed": "acme customer care"}}
    captured = {}

    class FakeSerpResults:
        def as_dict(self):
            return dict(payload)

    class FakeClient:
        def __init__(self, *, api_key=None, timeout=None):
            captured["api_key"] = api_key

        def search(self, params):
            captured["params"] = dict(params)
            return FakeSerpResults()

    import app.serpapi_client as serpapi_client_module

    monkeypatch.setattr(serpapi_client_module.serpapi, "Client", FakeClient)

    params = {"q": "acme customer care", "gl": "in", "hl": "en"}
    client = SerpApiClient(mode="live", fixtures_dir=tmp_path, api_key="test-key")
    result = client.search("google", params)

    assert result == payload
    assert captured["api_key"] == "test-key"
    assert captured["params"]["engine"] == "google"

    fixture = tmp_path / f"{build_cache_key('google', params)}.json"
    assert fixture.is_file()
    assert json.loads(fixture.read_text(encoding="utf-8")) == payload
    # replay can now serve the fixture the live call just recorded
    replay = SerpApiClient(mode="replay", fixtures_dir=tmp_path, api_key="")
    assert replay.search("google", params) == payload


def test_live_mode_requires_api_key(tmp_path):
    client = SerpApiClient(mode="live", fixtures_dir=tmp_path, api_key="")
    with pytest.raises(RuntimeError, match="SERPAPI_KEY"):
        client.search("google", {"q": "acme"})


def test_constructor_reads_mode_and_key_from_environment(monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "env-key")
    monkeypatch.setenv("SERPAPI_MODE", " LIVe ")

    client = SerpApiClient()
    assert client.api_key == "env-key"
    assert client.mode == "live"

    monkeypatch.setenv("SERPAPI_MODE", "")
    assert SerpApiClient().mode == "replay"

    monkeypatch.setenv("SERPAPI_MODE", "sometimes")
    with pytest.raises(ValueError, match="live"):
        SerpApiClient()
