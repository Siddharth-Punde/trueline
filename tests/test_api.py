"""Tests for app.api: TestClient against replay-mode fixtures only.

No test here touches the network: SERPAPI_MODE is pinned to "replay" and
every planned query's fixture is materialized into a tmp dir from the
committed synthetic Testco payloads (data/fixtures/testco_*.json). The brand
under scan is one of the committed fictional configs in data/brands/.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.models import Brand, EngineType, FindingKind, ScanResult
from app.query_planner import build_queries
from app.serpapi_client import fixture_path_for

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_DIR = REPO_ROOT / "data" / "brands"
RECORDED_FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"

BRAND_ID = "vastrakart"
COMMITTED_BRAND_IDS = {"vastrakart", "mediraksha", "khetsetu", "demobrand"}

SOURCE_FIXTURE = {
    EngineType.GOOGLE_SEARCH: "testco_search.json",
    EngineType.GOOGLE_MAPS: "testco_maps.json",
    EngineType.GOOGLE_LOCAL: "testco_local.json",
    EngineType.ADS_TRANSPARENCY: "testco_ads_transparency.json",
}
EMPTY_ADS_FIXTURE = "testco_ads_transparency_error.json"


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "fixtures"
    directory.mkdir()
    return directory


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path) -> TestClient:
    monkeypatch.setenv("SERPAPI_MODE", "replay")
    monkeypatch.setenv("TRUELINE_BRANDS_DIR", str(BRANDS_DIR))
    monkeypatch.setenv("TRUELINE_FIXTURES_DIR", str(fixtures_dir))
    return TestClient(api.create_app())


def record_fixtures(brand: Brand, fixtures_dir: Path, ads_fixture: str | None = None) -> None:
    """Materialize one fixture per planned query, keyed exactly as replay looks them up."""
    for query in build_queries(brand):
        source = SOURCE_FIXTURE[query.engine]
        if query.engine == EngineType.ADS_TRANSPARENCY and ads_fixture is not None:
            source = ads_fixture
        shutil.copyfile(
            RECORDED_FIXTURES_DIR / source,
            fixture_path_for(query.engine.value, query.params, fixtures_dir),
        )


def assert_well_formed(result: ScanResult) -> None:
    assert 0 <= result.trust_score <= 100
    assert result.scanned_at is not None
    evidence_ids = {ev.evidence_id for ev in result.evidence}
    assert evidence_ids, "scan produced no evidence at all"
    assert len(evidence_ids) == len(result.evidence)
    for finding in result.findings:
        assert finding.evidence_ids, "finding without evidence"
        assert set(finding.evidence_ids) <= evidence_ids
        assert finding.kind in set(FindingKind)
        assert 0.0 <= finding.confidence <= 1.0


# --- POST /scan ------------------------------------------------------------


def test_scan_returns_200_with_a_well_formed_scan_result(client, fixtures_dir):
    record_fixtures(api.load_brand(BRAND_ID), fixtures_dir)

    response = client.post("/scan", json={"brand_id": BRAND_ID})

    assert response.status_code == 200
    assert response.headers["x-serpapi-mode"] == "replay"
    result = ScanResult.model_validate(response.json())
    assert result.brand_id == BRAND_ID
    assert_well_formed(result)
    # the synthetic payloads contain numbers/domains the fictional brand does
    # not own, so scoring must surface findings rather than an empty report
    assert result.findings


def test_scan_with_zero_ads_transparency_evidence_is_still_200(client, fixtures_dir):
    brand = api.load_brand(BRAND_ID)
    record_fixtures(brand, fixtures_dir, ads_fixture=EMPTY_ADS_FIXTURE)

    response = client.post("/scan", json={"brand_id": BRAND_ID})

    assert response.status_code == 200
    result = ScanResult.model_validate(response.json())
    assert_well_formed(result)
    assert not [ev for ev in result.evidence if ev.engine == EngineType.ADS_TRANSPARENCY]


def test_scan_unknown_brand_is_404(client):
    response = client.post("/scan", json={"brand_id": "no-such-brand"})
    assert response.status_code == 404


def test_scan_refuses_path_like_brand_id(client):
    for sneaky in ("../brands/vastrakart", "..", "a/b"):
        assert client.post("/scan", json={"brand_id": sneaky}).status_code == 404


def test_scan_without_recorded_fixtures_is_409_not_a_crash(client):
    # nothing copied into fixtures_dir: replay has no data for this brand
    response = client.post("/scan", json={"brand_id": BRAND_ID})
    assert response.status_code == 409
    assert "fixture" in response.json()["detail"].lower()


def test_scan_request_cannot_opt_into_live_mode():
    # SERPAPI_MODE is env-only: a body field asking for live is rejected
    client = TestClient(api.create_app())
    response = client.post("/scan", json={"brand_id": BRAND_ID, "mode": "live"})
    assert response.status_code == 422


def test_scan_rejects_invalid_serpapi_mode_env(monkeypatch):
    monkeypatch.setenv("SERPAPI_MODE", "sometimes-live")
    response = TestClient(api.create_app()).post("/scan", json={"brand_id": BRAND_ID})
    assert response.status_code == 500
    assert "SERPAPI_MODE" in response.json()["detail"]


# --- GET / -----------------------------------------------------------------


def test_root_serves_the_web_ui(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "TrueLine" in response.text


# --- GET /brands -----------------------------------------------------------


def test_brands_lists_every_committed_brand_config(client):
    response = client.get("/brands")

    assert response.status_code == 200
    body = response.json()
    listed = {item["brand_id"] for item in body}
    # Superset, not equality: /brands serves every config on disk, and a
    # working copy may hold brands that are deliberately not committed here.
    assert COMMITTED_BRAND_IDS <= listed
    for item in body:
        assert set(item) == {"brand_id", "display_name"}
        assert item["display_name"].strip()


def test_committed_brand_configs_match_the_brand_model_exactly():
    for brand_id in sorted(COMMITTED_BRAND_IDS):
        raw = (BRANDS_DIR / f"{brand_id}.json").read_text(encoding="utf-8")
        brand = Brand.model_validate_json(raw)  # extra="forbid" enforces the contract
        assert brand.id == brand_id
        assert brand.official_domains and brand.official_phones
        # fictional placeholders only — reserved TLD + synthetic toll-free range
        assert all(domain.endswith(".example") for domain in brand.official_domains)
        assert all(re.fullmatch(r"\+9118000000\d\d", phone) for phone in brand.official_phones)


def test_brands_endpoint_rejects_an_invalid_config(client, tmp_path, monkeypatch):
    broken = tmp_path / "brands"
    broken.mkdir()
    (broken / "broken.json").write_text('{"id": "broken"}', encoding="utf-8")
    monkeypatch.setenv("TRUELINE_BRANDS_DIR", str(broken))

    assert TestClient(api.create_app()).get("/brands").status_code == 500


# --- GET /scan/{brand_id}/report -------------------------------------------


def test_report_returns_html_placeholder(client, fixtures_dir):
    record_fixtures(api.load_brand(BRAND_ID), fixtures_dir)

    response = client.get(f"/scan/{BRAND_ID}/report")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-serpapi-mode"] == "replay"
    assert BRAND_ID in response.text
    assert "trust score" in response.text.lower()


def test_report_for_unknown_brand_is_404(client):
    assert client.get("/scan/no-such-brand/report").status_code == 404


# --- CORS ------------------------------------------------------------------


def test_cors_allows_file_and_localhost_origins(client):
    for origin in ("null", "http://localhost:5173", "http://127.0.0.1:8000"):
        response = client.post(
            "/scan", json={"brand_id": BRAND_ID}, headers={"Origin": origin}
        )
        assert response.headers.get("access-control-allow-origin") in {"*", origin}


def test_cors_preflight_for_local_web_ui(client):
    response = client.options(
        "/scan",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") in {"*", "null"}


def test_scan_exposes_serpapi_mode_header_to_browser_js(client):
    # The web UI reads X-Serpapi-Mode in fetch(); CORS must expose it.
    response = client.post(
        "/scan", json={"brand_id": BRAND_ID}, headers={"Origin": "null"}
    )
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "X-Serpapi-Mode" in exposed


# --- scan flow / mode helpers ----------------------------------------------


def test_make_client_follows_serpapi_mode_env(monkeypatch):
    monkeypatch.setenv("SERPAPI_MODE", "replay")
    assert api.make_client().mode == "replay"
    monkeypatch.setenv("SERPAPI_MODE", "live")
    assert api.make_client().mode == "live"  # the only, explicit opt-in


def test_scan_brand_runs_collectors_then_scoring(fixtures_dir, monkeypatch):
    monkeypatch.setenv("SERPAPI_MODE", "replay")
    monkeypatch.setenv("TRUELINE_FIXTURES_DIR", str(fixtures_dir))
    brand = api.load_brand(BRAND_ID)
    record_fixtures(brand, fixtures_dir)

    result = api.scan_brand(BRAND_ID, client=api.make_client())

    assert result.brand_id == BRAND_ID
    assert_well_formed(result)


def test_render_report_html_returns_stable_html():
    from app.models import Brand
    brand = Brand(id="vastrakart", display_name="VastraKart", official_domains=["vastrakart.example"], official_phones=["+911800000001"])
    result = ScanResult(
        brand_id="vastrakart",
        scanned_at="2026-09-27T00:00:00+00:00",
        trust_score=80,
        findings=[],
        evidence=[],
    )
    html = api.render_report_html(result, brand)
    assert html == api.render_report_html(result, brand)
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "VastraKart" in html
