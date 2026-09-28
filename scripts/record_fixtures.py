"""CLI script to record real SerpApi fixtures into data/fixtures/.

Run once with SERPAPI_MODE=live and a valid SERPAPI_KEY in .env to populate
data/fixtures/ for every brand in data/brands/.  After recording, flip
SERPAPI_MODE=replay in .env so all subsequent runs use the saved fixtures.

Usage:
    SERPAPI_MODE=live SERPAPI_KEY=<your-key> python scripts/record_fixtures.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure repo root is on the path so "app" imports work when script is run
# directly (e.g. `python scripts/record_fixtures.py`).
if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collectors import run_all_collectors
from app.models import Brand
from app.query_planner import build_queries
from app.serpapi_client import SerpApiClient, DEFAULT_FIXTURES_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_DIR = REPO_ROOT / "data" / "brands"


def load_brands() -> list[Brand]:
    """Load all Brand models from data/brands/*.json."""
    brands: list[Brand] = []
    for path in sorted(BRANDS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        brands.append(Brand(**data))
    return brands


def main() -> None:
    brands = load_brands()
    if not brands:
        print("No brands found in data/brands/. Exiting.", file=sys.stderr)
        sys.exit(0)

    mode = os.getenv("SERPAPI_MODE", "replay").strip().lower()
    if mode != "live":
        print(
            f"SERPAPI_MODE is '{mode}', expected 'live'. "
            "Set SERPAPI_MODE=live and export SERPAPI_KEY first.",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.getenv("SERPAPI_KEY", "").strip()
    if not api_key:
        print("SERPAPI_KEY not set in environment. Exiting.", file=sys.stderr)
        sys.exit(1)

    client = SerpApiClient(api_key=api_key, mode="live")
    fixtures_dir = DEFAULT_FIXTURES_DIR

    for brand in brands:
        print(f"Recording fixtures for {brand.display_name} ({brand.id})...")
        queries = build_queries(brand)
        evidence = run_all_collectors(client, brand)
        # In live mode, SerpApiClient already saved every unique (engine, params)
        # payload to fixtures_dir. No manual follow-up needed.

    print("\nDone. Flip SERPAPI_MODE=replay in .env for subsequent runs.")


if __name__ == "__main__":
    main()