"""Tests for app.cli: argparse entrypoint, replay mode, readable output."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from app import cli
from app.api import load_brand
from app.models import EngineType, Finding, FindingKind
from app.query_planner import build_queries
from app.serpapi_client import fixture_path_for

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_DIR = REPO_ROOT / "data" / "brands"
RECORDED_FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"

BRAND_ID = "vastrakart"

SOURCE_FIXTURE = {
    EngineType.GOOGLE_SEARCH: "testco_search.json",
    EngineType.GOOGLE_MAPS: "testco_maps.json",
    EngineType.GOOGLE_LOCAL: "testco_local.json",
    EngineType.ADS_TRANSPARENCY: "testco_ads_transparency.json",
}


@pytest.fixture
def replay_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    monkeypatch.setenv("SERPAPI_MODE", "replay")
    monkeypatch.setenv("TRUELINE_BRANDS_DIR", str(BRANDS_DIR))
    monkeypatch.setenv("TRUELINE_FIXTURES_DIR", str(fixtures_dir))
    return fixtures_dir


def record_fixtures(fixtures_dir: Path) -> None:
    """Materialize one fixture per planned query, as replay expects to find them."""
    for query in build_queries(load_brand(BRAND_ID)):
        shutil.copyfile(
            RECORDED_FIXTURES_DIR / SOURCE_FIXTURE[query.engine],
            fixture_path_for(query.engine.value, query.params, fixtures_dir),
        )


def test_list_brands_prints_every_config(capsys):
    assert cli.main(["list-brands"]) == 0
    out = capsys.readouterr().out
    for brand_id in ("vastrakart", "mediraksha", "khetsetu"):
        assert brand_id in out
    assert "DISPLAY_NAME" in out


def test_scan_prints_trust_score_and_findings_table(replay_env, capsys):
    record_fixtures(replay_env)

    assert cli.main(["scan", BRAND_ID]) == 0

    out = capsys.readouterr().out
    assert f"Brand      : {BRAND_ID}" in out
    assert "Mode       : replay" in out
    assert "Trust score:" in out and "/100" in out
    assert "Findings (" in out
    assert "KIND" in out and "VALUE" in out and "CONF" in out
    # findings must trace to evidence ids from the scan
    assert "unofficial_" in out or "ad_off_domain" in out


def test_scan_demobrand_surfaces_the_four_planted_findings(capsys, monkeypatch):
    """The committed QuivoKart demo brand replays from data/fixtures/.

    Its hand-written payloads plant exactly one lookalike domain, one
    unofficial organic phone, one off-domain ad and one unclaimed maps
    listing, so the scan must surface four findings and a trust score
    clearly below the Air India scan's 65.
    """
    monkeypatch.setenv("SERPAPI_MODE", "replay")
    monkeypatch.setenv("TRUELINE_BRANDS_DIR", str(BRANDS_DIR))
    monkeypatch.setenv("TRUELINE_FIXTURES_DIR", str(RECORDED_FIXTURES_DIR))

    assert cli.main(["scan", "demobrand"]) == 0

    out = capsys.readouterr().out
    assert "Mode       : replay" in out
    assert "Findings (4):" in out
    for planted in ("quivokart-support.com", "quivo-kart.com", "+911800000088", "+911800000077"):
        assert planted in out
    match = re.search(r"Trust score: (\d+)/100", out)
    assert match and int(match.group(1)) < 65


def test_scan_unknown_brand_exits_nonzero(capsys):
    assert cli.main(["scan", "no-such-brand"]) == 4
    assert "error:" in capsys.readouterr().err


def test_scan_without_fixtures_exits_nonzero(capsys, replay_env):
    assert cli.main(["scan", BRAND_ID]) == 3
    assert "fixture" in capsys.readouterr().err.lower()


def test_scan_with_invalid_serpapi_mode_exits_nonzero(capsys, monkeypatch):
    monkeypatch.setenv("SERPAPI_MODE", "sometimes-live")
    assert cli.main(["scan", BRAND_ID]) == 2
    assert "SERPAPI_MODE" in capsys.readouterr().err


def test_format_findings_table_is_empty_for_no_findings():
    assert "No findings" in cli.format_findings_table([])


def test_format_findings_table_lists_every_finding():
    findings = [
        Finding(
            finding_id="a" * 16,
            kind=FindingKind.UNOFFICIAL_PHONE,
            value="+911800000099",
            evidence_ids=["e" * 64],
            confidence=0.8,
            explanation="Synthetic finding.",
        ),
        Finding(
            finding_id="b" * 16,
            kind=FindingKind.AD_OFF_DOMAIN,
            value="bad.example",
            evidence_ids=["f" * 64, "g" * 64],
            confidence=1.0,
            explanation="Synthetic finding two.",
        ),
    ]
    table = cli.format_findings_table(findings)
    assert table.count("\n") >= 3
    assert "+911800000099" in table and "bad.example" in table
    assert "Synthetic finding two." in table
