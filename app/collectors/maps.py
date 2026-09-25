"""Maps/Local collector: google_maps and google_local place listings.

Both engines answer with a `local_results` list of place items. Each listing
becomes one Evidence:
    title   <- name (`title`, falling back to `name`)
    link    <- website (the listing's own site; `link` as a fallback)
    snippet <- phone, so the number a customer would dial is on the record
    raw     <- the untouched original item, which keeps `unclaimed_listing`
               when SerpApi reports it (a real field found in testing, and a
               trust signal consumed by the scoring pass)
"""

from __future__ import annotations

from typing import Any

from app.collectors.common import (
    SearchClient,
    as_opt_str,
    as_str,
    build_evidence,
    fetch_payload,
    ranked_position,
)
from app.models import Evidence, PlannedQuery

# engine=google nests its local pack under one of these; google_maps and
# google_local return a bare list. Accept both shapes.
_NESTED_LIST_KEYS = ("places", "place_results", "results")


def place_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The place listings of one local response, normalized to a list."""
    local = payload.get("local_results")
    if isinstance(local, dict):
        local = next(
            (local[key] for key in _NESTED_LIST_KEYS if isinstance(local.get(key), list)),
            [],
        )
    if not isinstance(local, list):
        return []
    return [item for item in local if isinstance(item, dict)]


def _place_evidence(query: PlannedQuery, item: dict[str, Any], index: int) -> Evidence:
    return build_evidence(
        engine=query.engine,
        query=query.query_text,
        is_ad=False,
        position=ranked_position(item, index),
        title=as_str(item.get("title") or item.get("name")),
        link=as_opt_str(item.get("website")) or as_opt_str(item.get("link")),
        snippet=as_opt_str(item.get("phone")),
        raw=item,
    )


def collect_maps(client: SearchClient, queries: list[PlannedQuery]) -> list[Evidence]:
    """Parse place listings for every google_maps / google_local query."""
    evidence: list[Evidence] = []
    for query in queries:
        payload = fetch_payload(client, query)
        evidence.extend(
            _place_evidence(query, item, index)
            for index, item in enumerate(place_items(payload))
        )
    return evidence
