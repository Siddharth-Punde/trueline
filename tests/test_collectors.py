"""Tests for app.collectors: hand-written per-engine fixtures -> Evidence.

Every payload here is synthetic (fake brand "Testco", fake numbers of the
form 1800-000-00xx, reserved .example domains) — never a real business
(AGENTS.md). No test touches the network: fakes serve the fixtures directly,
and the one end-to-end test runs the real SerpApiClient in replay mode
against a tmp copy of them.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from app.collectors import (
    collect_ads_transparency,
    collect_maps,
    collect_search,
    run_all_collectors,
)
from app.collectors.common import (
    as_opt_str,
    as_str,
    dict_items,
    fetch_payload,
    make_evidence_id,
    ranked_position,
)
from app.models import Brand, EngineType, Evidence, PlannedQuery
from app.query_planner import build_queries
from app.serpapi_client import SerpApiClient, fixture_path_for

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"

TESTCO = Brand(
    id="testco",
    display_name="Testco",
    official_domains=["testco.example"],
    official_phones=["+911800000000"],
    aliases=[],
)

SEARCH_FIXTURE = "testco_search.json"
MAPS_FIXTURE = "testco_maps.json"
LOCAL_FIXTURE = "testco_local.json"
ADS_FIXTURE = "testco_ads_transparency.json"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def queries_for(engine: EngineType) -> list[PlannedQuery]:
    """The real planner's queries for TESTCO, filtered to one engine."""
    return [q for q in build_queries(TESTCO) if q.engine == engine]


def first_query(engine: EngineType) -> PlannedQuery:
    return queries_for(engine)[0]


class FakeClient:
    """Stands in for SerpApiClient: serves fixture payloads keyed by engine."""

    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict]] = []

    def search(self, engine: str, params: dict) -> dict:
        self.calls.append((engine, dict(params)))
        return self.payloads[engine]


def assert_evidence_shape(evidence: list[Evidence]) -> None:
    for ev in evidence:
        assert isinstance(ev, Evidence)
        assert isinstance(ev.evidence_id, str) and len(ev.evidence_id) == 64
        assert isinstance(ev.raw, dict) and ev.raw
        assert isinstance(ev.is_ad, bool)
        assert ev.query
        assert ev.position is None or isinstance(ev.position, int)
        assert set(ev.model_dump()) == {
            "evidence_id",
            "engine",
            "query",
            "is_ad",
            "position",
            "title",
            "link",
            "snippet",
            "raw",
        }


def search_evidence() -> list[Evidence]:
    client = FakeClient({EngineType.GOOGLE_SEARCH.value: load_fixture(SEARCH_FIXTURE)})
    return collect_search(client, [first_query(EngineType.GOOGLE_SEARCH)])


# --- google_search ---------------------------------------------------------


def test_collect_search_parses_organic_ads_answer_box_and_featured_snippet():
    payload = load_fixture(SEARCH_FIXTURE)
    client = FakeClient({EngineType.GOOGLE_SEARCH.value: payload})
    query = first_query(EngineType.GOOGLE_SEARCH)

    evidence = collect_search(client, [query])

    assert client.calls == [("google_search", query.params)]
    assert len(evidence) == 7  # 3 organic + 2 ads + 1 answer box + 1 featured snippet
    assert_evidence_shape(evidence)
    assert all(ev.engine == EngineType.GOOGLE_SEARCH for ev in evidence)
    assert all(ev.query == query.query_text for ev in evidence)

    assert [ev.title for ev in evidence] == [
        "Testco - Official Website",
        "Testco Third-Party Support Desk",
        "Testco Complaint Forum",
        "Testco Support Helpline - Call Now",
        "Testco Refund Desk",
        "Testco customer care number",
        "Contact Testco",
    ]
    # organic keeps its real rank, ads keep theirs
    assert [ev.position for ev in evidence[:3]] == [1, 2, 11]
    assert [ev.position for ev in evidence[3:5]] == [1, 2]
    # only the ads array is flagged as advertising
    assert [ev.is_ad for ev in evidence] == [False, False, False, True, True, False, False]
    # answer box and featured snippet carry no organic rank
    assert evidence[5].position is None
    assert evidence[6].position is None
    # raw is the untouched original SERP item
    assert evidence[0].raw == payload["organic_results"][0]
    assert evidence[3].raw == payload["ads"][0]


def test_collect_search_featured_snippet_holds_the_phone_text():
    evidence = search_evidence()
    featured = [ev for ev in evidence if ev.raw.get("type") == "featured_snippet"]

    assert len(featured) == 1
    assert "toll-free number 1800-000-0005" in featured[0].snippet
    assert featured[0].link == "https://contact.testco.example/toll-free"


def test_collect_search_skips_ai_overview_related_questions():
    payload = load_fixture(SEARCH_FIXTURE)
    evidence = search_evidence()

    assert payload["related_questions"][1]["type"] == "ai_overview"
    assert all(ev.raw.get("type") != "ai_overview" for ev in evidence)
    # no evidence ever points at the skipped item
    assert all(ev.raw != payload["related_questions"][1] for ev in evidence)


def test_collect_search_empty_payload_returns_empty_list():
    client = FakeClient({EngineType.GOOGLE_SEARCH.value: {}})
    assert collect_search(client, [first_query(EngineType.GOOGLE_SEARCH)]) == []


def test_evidence_id_is_stable_sha256_of_engine_query_position_title():
    evidence = search_evidence()
    organic = next(ev for ev in evidence if ev.title == "Testco - Official Website")

    expected = hashlib.sha256(
        json.dumps(
            ["google_search", "Testco customer care number", 1, "Testco - Official Website"],
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    assert organic.evidence_id == expected

    rerun = search_evidence()
    assert [ev.evidence_id for ev in rerun] == [ev.evidence_id for ev in evidence]

    featured = next(ev for ev in evidence if ev.title == "Contact Testco")
    assert featured.evidence_id == make_evidence_id(
        EngineType.GOOGLE_SEARCH, featured.query, None, "Contact Testco"
    )
    assert len({ev.evidence_id for ev in evidence}) == len(evidence)


# --- google_maps / google_local -------------------------------------------


def test_collect_maps_parses_name_phone_website_and_rank():
    payload = load_fixture(MAPS_FIXTURE)
    client = FakeClient({EngineType.GOOGLE_MAPS.value: payload})
    query = first_query(EngineType.GOOGLE_MAPS)

    evidence = collect_maps(client, [query])

    assert client.calls == [("google_maps", query.params)]
    assert len(evidence) == 3
    assert_evidence_shape(evidence)
    assert all(ev.engine == EngineType.GOOGLE_MAPS for ev in evidence)
    assert all(ev.is_ad is False for ev in evidence)
    assert [ev.position for ev in evidence] == [1, 2, 3]

    official = evidence[0]
    assert official.title == "Testco Customer Care (Official)"
    assert official.snippet == "1800-000-0001"  # phone surfaced on the record
    assert official.link == "https://www.testco.example/help"
    assert official.raw == payload["local_results"][0]


def test_collect_maps_carries_unclaimed_listing_through_raw():
    payload = load_fixture(MAPS_FIXTURE)
    evidence = collect_maps(
        FakeClient({EngineType.GOOGLE_MAPS.value: payload}),
        [first_query(EngineType.GOOGLE_MAPS)],
    )

    unclaimed = next(ev for ev in evidence if ev.title == "Testco Support Desk (Unofficial)")
    assert unclaimed.raw["unclaimed_listing"] is True
    assert "unclaimed_listing" not in evidence[0].raw
    # listing without a website keeps link=None but still carries its phone
    no_website = evidence[2]
    assert no_website.link is None
    assert no_website.snippet == "1800-000-0010"


def test_collect_maps_parses_google_local_results():
    payload = load_fixture(LOCAL_FIXTURE)
    client = FakeClient({EngineType.GOOGLE_LOCAL.value: payload})

    evidence = collect_maps(client, [first_query(EngineType.GOOGLE_LOCAL)])

    assert len(evidence) == 2
    assert_evidence_shape(evidence)
    assert all(ev.engine == EngineType.GOOGLE_LOCAL for ev in evidence)
    assert evidence[0].title == "Testco Help Centre"
    assert evidence[0].snippet == "1800-000-0006"
    assert evidence[0].link == "https://help.testco.example"
    assert evidence[1].raw["unclaimed_listing"] is True
    assert evidence[1].raw == payload["local_results"][1]


def test_collect_maps_accepts_nested_places_shape():
    payload = {"local_results": {"places": [
        {"position": 1, "title": "Testco Kiosk", "phone": "1800-000-0012"}
    ]}}
    evidence = collect_maps(
        FakeClient({EngineType.GOOGLE_MAPS.value: payload}),
        [first_query(EngineType.GOOGLE_MAPS)],
    )

    assert [ev.title for ev in evidence] == ["Testco Kiosk"]
    assert evidence[0].snippet == "1800-000-0012"


def test_collect_maps_empty_payload_returns_empty_list():
    client = FakeClient({EngineType.GOOGLE_MAPS.value: {}})
    assert collect_maps(client, [first_query(EngineType.GOOGLE_MAPS)]) == []


# --- ads_transparency ------------------------------------------------------


def test_collect_ads_transparency_one_evidence_per_distinct_advertiser():
    payload = load_fixture(ADS_FIXTURE)
    client = FakeClient({EngineType.ADS_TRANSPARENCY.value: payload})
    query = first_query(EngineType.ADS_TRANSPARENCY)

    evidence = collect_ads_transparency(client, [query])

    assert client.calls == [("ads_transparency", query.params)]
    # "Testco Official" appears in the advertiser block AND a creative, but
    # only one Evidence is emitted per distinct advertiser
    assert len(evidence) == 2
    assert [ev.title for ev in evidence] == ["Testco Official", "Testco Resellers Hub"]
    assert [ev.position for ev in evidence] == [1, 2]
    assert_evidence_shape(evidence)
    assert all(ev.engine == EngineType.ADS_TRANSPARENCY for ev in evidence)
    assert all(ev.is_ad is True for ev in evidence)
    assert evidence[0].raw == payload["advertiser"]
    assert evidence[1].raw == payload["ad_creatives"][1]
    # creative links are Google-hosted previews, never the advertiser's domain
    assert all(ev.link is None for ev in evidence)


def test_collect_ads_transparency_error_response_is_a_normal_empty_result():
    payload = load_fixture("testco_ads_transparency_error.json")
    assert "hasn't returned any results" in payload["error"]

    client = FakeClient({EngineType.ADS_TRANSPARENCY.value: payload})
    assert collect_ads_transparency(client, [first_query(EngineType.ADS_TRANSPARENCY)]) == []


def test_collect_ads_transparency_empty_payload_is_a_normal_empty_result():
    client = FakeClient({EngineType.ADS_TRANSPARENCY.value: {}})
    assert collect_ads_transparency(client, [first_query(EngineType.ADS_TRANSPARENCY)]) == []


# --- routing ---------------------------------------------------------------


def test_run_all_collectors_routes_every_planned_query(tmp_path):
    fixture_by_engine = {
        EngineType.GOOGLE_SEARCH: SEARCH_FIXTURE,
        EngineType.GOOGLE_MAPS: MAPS_FIXTURE,
        EngineType.GOOGLE_LOCAL: LOCAL_FIXTURE,
        EngineType.ADS_TRANSPARENCY: ADS_FIXTURE,
    }
    planned = build_queries(TESTCO)
    # no aliases: 5 search + 1 ads + 1 maps + 1 local
    assert len(planned) == 8
    for query in planned:
        shutil.copyfile(
            FIXTURES_DIR / fixture_by_engine[query.engine],
            fixture_path_for(query.engine.value, query.params, tmp_path),
        )

    client = SerpApiClient(mode="replay", fixtures_dir=tmp_path, api_key="")
    evidence = run_all_collectors(client, TESTCO)

    assert len(evidence) == 5 * 7 + 2 + 3 + 2
    assert_evidence_shape(evidence)
    assert dict(Counter(ev.engine for ev in evidence)) == {
        EngineType.GOOGLE_SEARCH: 35,
        EngineType.ADS_TRANSPARENCY: 2,
        EngineType.GOOGLE_MAPS: 3,
        EngineType.GOOGLE_LOCAL: 2,
    }
    # ids stay unique across engines and across the five different queries
    assert len({ev.evidence_id for ev in evidence}) == len(evidence)


# --- shared helpers (app.collectors.common) --------------------------------


def test_ranked_position_prefers_the_items_own_rank():
    assert ranked_position({"position": 7}, 0) == 7
    assert ranked_position({}, 2) == 3  # 1-based place in the list
    assert ranked_position({"position": True}, 0) == 1  # bool is not a rank


def test_dict_items_normalizes_list_dict_and_absent_values():
    assert dict_items([{"a": 1}, "skip", 2]) == [{"a": 1}]
    assert dict_items({"a": 1}) == [{"a": 1}]
    assert dict_items(None) == []
    assert dict_items("nope") == []


def test_text_helpers_coerce_and_filter():
    assert as_str("title") == "title"
    assert as_str(None) == ""
    assert as_str(7) == "7"
    assert as_opt_str("link") == "link"
    assert as_opt_str(7) is None


def test_fetch_payload_treats_a_non_dict_response_as_empty():
    class ListClient:
        def search(self, engine, params):
            return ["not", "a", "dict"]

    query = first_query(EngineType.GOOGLE_SEARCH)
    assert fetch_payload(ListClient(), query) == {}


def test_make_evidence_id_differs_on_every_component():
    base = make_evidence_id(EngineType.GOOGLE_SEARCH, "q", 1, "t")
    assert len(base) == 64
    assert make_evidence_id(EngineType.GOOGLE_SEARCH, "q", 2, "t") != base
    assert make_evidence_id(EngineType.GOOGLE_SEARCH, "q", None, "t") != base
    assert make_evidence_id(EngineType.GOOGLE_SEARCH, "other", 1, "t") != base
    assert make_evidence_id(EngineType.GOOGLE_MAPS, "q", 1, "t") != base
    assert make_evidence_id("google_search", "q", 1, "t") == base


def test_collect_search_payload_missing_organic():
    # Payload with no organic_results key returns empty evidence.
    client = FakeClient({EngineType.GOOGLE_SEARCH.value: {"ads": []}})
    assert collect_search(client, [first_query(EngineType.GOOGLE_SEARCH)]) == []


def test_collect_search_payload_with_malformed_items():
    # Items missing title/link/snippet still produce evidence with empty defaults.
    payload = {
        "organic_results": [{"some_field": "value"}],
        "ads": [],
        "answer_box": [],
        "related_questions": [],
    }
    client = FakeClient({EngineType.GOOGLE_SEARCH.value: payload})
    evidence = collect_search(client, [first_query(EngineType.GOOGLE_SEARCH)])
    assert len(evidence) == 1
    # as_str(None) -> "" when key is absent
    assert evidence[0].title == ""


def test_collect_maps_place_missing_fields():
    # A place item missing some fields still produces evidence with defaults.
    payload = {"local_results": [{"title": "Partial Place", "phone": "1800-000-0099"}]}
    client = FakeClient({EngineType.GOOGLE_MAPS.value: payload})
    query = first_query(EngineType.GOOGLE_MAPS)
    evidence = collect_maps(client, [query])
    assert len(evidence) == 1
    assert evidence[0].title == "Partial Place"
    assert evidence[0].snippet == "1800-000-0099"
    assert evidence[0].link is None


def test_collect_maps_empty_local_results():
    # local_results is an empty list returns no evidence.
    payload = {"local_results": []}
    client = FakeClient({EngineType.GOOGLE_MAPS.value: payload})
    assert collect_maps(client, [first_query(EngineType.GOOGLE_MAPS)]) == []


def test_collect_ads_transparency_item_missing_name():
    # An item with no advertiser name field is skipped.
    payload = {"ad_creatives": [{"some_other_field": "value"}]}
    client = FakeClient({EngineType.ADS_TRANSPARENCY.value: payload})
    query = first_query(EngineType.ADS_TRANSPARENCY)
    evidence = collect_ads_transparency(client, [query])
    assert evidence == []


def test_collect_ads_transparency_payload_with_error():
    # Payload with "error" key returns no evidence (normal empty result).
    payload = {"error": "Some error message"}
    client = FakeClient({EngineType.ADS_TRANSPARENCY.value: payload})
    query = first_query(EngineType.ADS_TRANSPARENCY)
    assert collect_ads_transparency(client, [query]) == []
