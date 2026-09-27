"""FastAPI surface for TrueLine: /scan, /brands and the HTML report.

Mode policy (the point of this module): SERPAPI_MODE in the environment is
the ONLY thing that chooses replay vs live. The scan flow builds its client
from the env via make_client() and the request body cannot override it, so a
caller who did not export SERPAPI_MODE=live can never spend a live credit —
and the active mode is echoed in the X-Serpapi-Mode response header, so the
caller always sees which mode served them.

Zero Ads Transparency evidence is a normal, expected outcome (SPEC:
best-effort engine), never an error: /scan returns 200 with whatever evidence
the other engines produced.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import report as report_module
from app.collectors import run_all_collectors
from app.models import Brand, ScanResult
from app.serpapi_client import FixtureMissingError, SerpApiClient
from app.verify import score_and_verify

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BRANDS_DIR = REPO_ROOT / "data" / "brands"

BRAND_FILE_SUFFIX = ".json"


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # No mode field on purpose: live/replay comes from the env only.
    brand_id: str = Field(min_length=1)


class BrandSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_id: str
    display_name: str


def brands_dir() -> Path:
    """Where brand configs live; env override exists so tests can be hermetic."""
    return Path(os.getenv("TRUELINE_BRANDS_DIR") or DEFAULT_BRANDS_DIR)


def _brand_path(brand_id: str) -> Path | None:
    """Resolve a brand id to its config file, refusing anything path-like."""
    if not brand_id or any(token in brand_id for token in ("/", "\\", "..")):
        return None
    path = brands_dir() / f"{brand_id}{BRAND_FILE_SUFFIX}"
    # Belt and braces: the resolved file must still sit inside brands_dir().
    if path.parent.resolve() != brands_dir().resolve():
        return None
    return path


def load_brand(brand_id: str) -> Brand:
    path = _brand_path(brand_id)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"No brand config named {brand_id!r} in {brands_dir()}")
    try:
        return Brand.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValueError(f"Invalid brand config {path.name}: {exc}") from exc


def list_brands() -> list[BrandSummary]:
    """Every brand config in brands_dir(), sorted by id, invalid ones rejected."""
    directory = brands_dir()
    if not directory.is_dir():
        return []
    summaries: list[BrandSummary] = []
    for path in sorted(directory.glob(f"*{BRAND_FILE_SUFFIX}")):
        brand = load_brand(path.stem)
        if brand.id != path.stem:
            # /scan addresses brands by filename stem, so a mismatch would 404
            raise ValueError(f"Brand config {path.name} declares id={brand.id!r}")
        summaries.append(BrandSummary(brand_id=brand.id, display_name=brand.display_name))
    return sorted(summaries, key=lambda s: s.brand_id)


def make_client() -> SerpApiClient:
    """Replay/live decided by SERPAPI_MODE in the env (default: replay)."""
    return SerpApiClient(fixtures_dir=os.getenv("TRUELINE_FIXTURES_DIR") or None)


def scan_brand(brand_id: str, *, client: SerpApiClient) -> ScanResult:
    """The one scan flow: brand config -> collectors -> scoring."""
    brand = load_brand(brand_id)
    evidence = run_all_collectors(client, brand)
    return score_and_verify(brand, evidence)


def render_report_html(result: ScanResult, brand: Brand) -> str:
    """HTML for a ScanResult via app/report.py."""
    return report_module.render_html_report(result, brand)


def _client_or_http() -> SerpApiClient:
    try:
        return make_client()
    except ValueError as exc:  # bad SERPAPI_MODE value
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _scan_or_http(client: SerpApiClient, brand_id: str) -> ScanResult:
    try:
        return scan_brand(brand_id, client=client)
    except FixtureMissingError as exc:  # must precede FileNotFoundError (it subclasses it)
        raise HTTPException(
            status_code=409,
            detail=(
                "Replay mode has no fixture for this brand's queries yet. "
                f"{exc} Record them once with SERPAPI_MODE=live, then replay."
            ),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def create_app() -> FastAPI:
    application = FastAPI(title="TrueLine", version="0.1.0")
    # The local web/ UI may be opened as file:// (Origin: "null") or served
    # from localhost; both must be able to call this API.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @application.post("/scan", response_model=ScanResult)
    def scan(request: ScanRequest, response: Response) -> ScanResult:
        client = _client_or_http()
        result = _scan_or_http(client, request.brand_id)
        response.headers["X-Serpapi-Mode"] = client.mode
        return result

    @application.get("/brands", response_model=list[BrandSummary])
    def brands() -> list[BrandSummary]:
        try:
            return list_brands()
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @application.get("/scan/{brand_id}/report")
    def report(brand_id: str) -> Response:
        client = _client_or_http()
        result = _scan_or_http(client, brand_id)
        brand = load_brand(brand_id)
        return Response(
            content=render_report_html(result, brand),
            media_type="text/html; charset=utf-8",
            headers={"X-Serpapi-Mode": client.mode},
        )

    return application


app = create_app()
