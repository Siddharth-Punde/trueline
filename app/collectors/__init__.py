"""Engine collectors: run a brand's PlannedQuery list and gather Evidence.

build_queries() plans five engine surfaces per brand; this package routes
each planned query to the collector that knows how to parse its response:

    google_search      -> collect_search
    google_maps        -> collect_maps
    google_local       -> collect_maps   (same local_results shape)
    ads_transparency   -> collect_ads_transparency

Every collector takes (client, queries already filtered to its engine) and
returns Evidence with stable sha256 ids over (engine, query, position, title).
"""

from __future__ import annotations

from collections.abc import Callable

from app.collectors.ads_transparency import collect_ads_transparency
from app.collectors.common import SearchClient, make_evidence_id
from app.collectors.maps import collect_maps
from app.collectors.search import collect_search
from app.models import Brand, EngineType, Evidence, PlannedQuery
from app.query_planner import build_queries

Collector = Callable[[SearchClient, list[PlannedQuery]], list[Evidence]]

ENGINE_ROUTES: dict[EngineType, Collector] = {
    EngineType.GOOGLE_SEARCH: collect_search,
    EngineType.GOOGLE_MAPS: collect_maps,
    EngineType.GOOGLE_LOCAL: collect_maps,
    EngineType.ADS_TRANSPARENCY: collect_ads_transparency,
}


def run_all_collectors(client: SearchClient, brand: Brand) -> list[Evidence]:
    """Collect evidence from every engine for one brand, in planning order."""
    grouped: dict[EngineType, list[PlannedQuery]] = {}
    for planned in build_queries(brand):
        grouped.setdefault(planned.engine, []).append(planned)

    evidence: list[Evidence] = []
    for engine, queries in grouped.items():
        collector = ENGINE_ROUTES.get(engine)
        if collector is None:
            raise KeyError(f"No collector routed for engine {engine.value!r}")
        evidence.extend(collector(client, queries))
    return evidence


__all__ = [
    "ENGINE_ROUTES",
    "collect_ads_transparency",
    "collect_maps",
    "collect_search",
    "make_evidence_id",
    "run_all_collectors",
]
