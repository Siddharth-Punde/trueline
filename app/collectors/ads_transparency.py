"""Ads Transparency collector: one Evidence per distinct advertiser.

The lookup is a free-text search on the brand's official domain (see
query_planner._ads_query), so a response can carry the resolved `advertiser`
block plus a creative list (`ad_creatives`), or an advertiser list, or — most
often for real brands — just an `error` such as:

    {"error": "... hasn't returned any results for your query. ..."}

That empty answer is the expected, normal outcome for this engine (SPEC:
best-effort, never block a scan), so it returns [] instead of raising.

Advertisers are deduplicated by name within one query: N creatives from the
same advertiser are one advertiser, not N.
"""

from __future__ import annotations

from typing import Any

from app.collectors.common import (
    SearchClient,
    as_opt_str,
    build_evidence,
    dict_items,
    fetch_payload,
)
from app.extract import extract_advertiser_name
from app.models import Evidence, PlannedQuery

# Checked in order: advertiser lists first (the ranked advertisers), then the
# creative list, so the first occurrence of a name sets its position.
_LIST_CONTAINER_KEYS = (
    "advertisers",
    "advertiser_results",
    "results",
    "ads_results",
    "ad_creatives",
    "ads",
    "creatives",
)


def candidate_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every item that may name an advertiser, in response order."""
    if payload.get("error"):
        return []
    items: list[dict[str, Any]] = []
    advertiser = payload.get("advertiser")
    if isinstance(advertiser, dict):
        items.append(advertiser)
    for key in _LIST_CONTAINER_KEYS:
        items.extend(dict_items(payload.get(key)))
    return items


def collect_ads_transparency(
    client: SearchClient, queries: list[PlannedQuery]
) -> list[Evidence]:
    """One Evidence per distinct advertiser found for each domain lookup."""
    evidence: list[Evidence] = []
    for query in queries:
        payload = fetch_payload(client, query)
        seen: set[str] = set()
        for item in candidate_items(payload):
            name = extract_advertiser_name(item)
            if name is None or name in seen:
                continue
            seen.add(name)
            evidence.append(
                build_evidence(
                    engine=query.engine,
                    query=query.query_text,
                    is_ad=True,
                    position=len(seen),
                    title=name,
                    # Deliberately None: the creative `link` is a Google-hosted
                    # preview URL (displayads-formats.googleusercontent.com)
                    # and `details_link` is adstransparency.google.com — either
                    # would be misread as the advertiser's own domain by the
                    # off-domain check. Both stay available in raw.
                    link=None,
                    snippet=as_opt_str(item.get("snippet"))
                    or as_opt_str(item.get("ad_text")),
                    raw=item,
                )
            )
    return evidence
