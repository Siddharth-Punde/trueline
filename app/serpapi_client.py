"""SerpApi access layer — the ONLY module allowed to hit the real API (AGENTS.md).

Engine aliases -> real SerpApi `engine` values, verified against the docs at
serpapi.com/search-api, serpapi.com/google-maps-api, serpapi.com/google-local-api
and serpapi.com/google-ads-transparency-center-api:

    google                  -> google
    google_search           -> google
    google_maps             -> google_maps
    google_local            -> google_local
    google_ads_transparency -> google_ads_transparency_center  (no engine named "google_ads_transparency" exists)
    ads_transparency        -> google_ads_transparency_center
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import serpapi
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"

ENGINE_ALIASES: dict[str, str] = {
    "google": "google",
    "google_search": "google",
    "google_maps": "google_maps",
    "google_local": "google_local",
    "google_ads_transparency": "google_ads_transparency_center",
    "ads_transparency": "google_ads_transparency_center",
    "google_ads_transparency_center": "google_ads_transparency_center",
}


class FixtureMissingError(FileNotFoundError):
    """Replay mode was asked for a fixture that was never recorded."""

    def __init__(self, fixture_path: Path, engine: str, cache_key: str):
        self.fixture_path = fixture_path
        self.engine = engine
        self.cache_key = cache_key
        super().__init__(
            f"Replay mode: no fixture for engine '{engine}' (cache_key={cache_key}). "
            f"Missing file: {fixture_path}. "
            f"Record it once with SERPAPI_MODE=live, then run again in replay mode."
        )


def resolve_engine(engine: str) -> str:
    """Map a caller-facing engine name onto the real SerpApi engine name."""
    return ENGINE_ALIASES.get(engine, engine)


def build_cache_key(engine: str, params: dict[str, Any]) -> str:
    """sha256 over engine + params sorted by key, so key order never matters."""
    canonical = json.dumps(
        {"engine": resolve_engine(engine), "params": params},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fixture_path_for(engine: str, params: dict[str, Any], fixtures_dir: Path | None = None) -> Path:
    """Where the raw response for this engine/params pair is (or will be) stored."""
    base = fixtures_dir if fixtures_dir is not None else DEFAULT_FIXTURES_DIR
    return base / f"{build_cache_key(engine, params)}.json"


class SerpApiClient:
    """Wraps the official `serpapi` package behind a replay/live fixture cache.

    replay (default): read data/fixtures/{cache_key}.json, never touch the network.
    live: call SerpApi, ALWAYS save the raw response to data/fixtures/{cache_key}.json
          before returning it, so one paid query is replayable forever.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        mode: str | None = None,
        fixtures_dir: str | Path | None = None,
        client: Any | None = None,
    ) -> None:
        load_dotenv()
        self.api_key = api_key if api_key is not None else os.getenv("SERPAPI_KEY") or ""
        raw_mode = mode if mode is not None else os.getenv("SERPAPI_MODE") or "replay"
        self.mode = str(raw_mode).strip().lower()
        if self.mode not in {"live", "replay"}:
            raise ValueError(f"SERPAPI_MODE must be 'live' or 'replay', got {raw_mode!r}")
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir is not None else DEFAULT_FIXTURES_DIR
        # Built lazily so replay mode never needs a key or a network stack.
        self._client = client

    def search(self, engine: str, params: dict[str, Any]) -> dict[str, Any]:
        real_engine = resolve_engine(engine)
        cache_key = build_cache_key(real_engine, params)
        path = fixture_path_for(real_engine, params, self.fixtures_dir)

        if self.mode == "replay":
            if not path.is_file():
                raise FixtureMissingError(path, real_engine, cache_key)
            return json.loads(path.read_text(encoding="utf-8"))

        payload = self._fetch_live(real_engine, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return payload

    def _fetch_live(self, engine: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "SERPAPI_KEY is not set (.env / environment); live mode cannot call SerpApi."
            )
        if self._client is None:
            self._client = serpapi.Client(api_key=self.api_key)

        request_params = dict(params)  # serpapi.Client.search() mutates its argument
        request_params["engine"] = engine
        results = self._client.search(request_params)

        if hasattr(results, "as_dict"):
            return results.as_dict()
        if isinstance(results, dict):
            return dict(results)
        raise RuntimeError(
            f"SerpApi returned a non-JSON response for engine={engine!r} "
            f"(got {type(results).__name__}); expected a dict / SerpResults."
        )
