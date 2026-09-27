"""Builds the PlannedQuery list described in SPEC.md § Query templates.

Per brand and each alias: the five free-text templates on Google Search with
India geo params (gl=in, hl=en); one Ads Transparency lookup keyed on
official_domains[0]; one google_maps query and one google_local query using
"{name} customer care" with an India-wide location bias.
"""

from __future__ import annotations

from app.models import Brand, EngineType, PlannedQuery

REGION_PARAMS: dict[str, str] = {"gl": "in", "hl": "en"}

QUERY_TEMPLATES: tuple[str, ...] = (
    "{name} customer care number",
    "{name} customer care",
    "{name} refund",
    "{name} complaint number",
    "{name} toll free number",
)

MAPS_LOCAL_QUERY = "{name} customer care"

# Center of India in the documented `ll` format "@lat,lon,zoom"
# (serpapi.com/google-maps-api). Zoom 4 is country-wide; docs set 3z as the
# minimum. VERIFY in the SerpApi Playground: docs warn results are "not
# guaranteed to be within the requested geographic location".
INDIA_MAPS_LL = "@20.5937,78.9629,4z"




def _names(brand: Brand) -> list[str]:
    names: list[str] = []
    for candidate in [brand.display_name, *brand.aliases]:
        if candidate and candidate not in names:
            names.append(candidate)
    return names


def _search_queries(name: str) -> list[PlannedQuery]:
    queries = []
    for template in QUERY_TEMPLATES:
        text = template.format(name=name)
        queries.append(
            PlannedQuery(
                engine=EngineType.GOOGLE_SEARCH,
                query_text=text,
                params={**REGION_PARAMS, "q": text},
            )
        )
    return queries


def _ads_query(brand: Brand) -> PlannedQuery | None:
    if not brand.official_domains:
        # Ads Transparency is best-effort (SPEC), so a domain-less brand just
        # gets no ads query instead of a planning error.
        return None
    domain = brand.official_domains[0]
    # Verified in the SerpApi Playground (Run 4/5): engine
    # "google_ads_transparency_center" with advertiser_id=<domain> returns a
    # valid structured response. The earlier free-text {"text", "region"}
    # shape was the one that failed; `advertiser_id` accepting a bare domain
    # (not only AR-prefixed ids) is what the real run confirmed. Empty
    # results for a known-good advertiser_id are expected (SPEC:
    # best-effort), not a param error.
    return PlannedQuery(
        engine=EngineType.ADS_TRANSPARENCY,
        query_text=domain,
        params={"advertiser_id": domain},
    )


def _maps_query(name: str) -> PlannedQuery:
    text = MAPS_LOCAL_QUERY.format(name=name)
    return PlannedQuery(
        engine=EngineType.GOOGLE_MAPS,
        query_text=text,
        params={**REGION_PARAMS, "q": text, "type": "search", "ll": INDIA_MAPS_LL},
    )


def _local_query(name: str) -> PlannedQuery:
    text = MAPS_LOCAL_QUERY.format(name=name)
    # VERIFY in the SerpApi Playground: `location` accepts free-form text, but
    # SerpApi recommends city level "to simulate a real user's search" — a
    # country-level "India" is our intentional India-wide bias (alternative:
    # the `uule` country code, which I do not want to guess at here).
    return PlannedQuery(
        engine=EngineType.GOOGLE_LOCAL,
        query_text=text,
        params={**REGION_PARAMS, "q": text, "location": "India"},
    )


def build_queries(brand: Brand) -> list[PlannedQuery]:
    """Return every PlannedQuery for one brand, in SPEC.md order."""
    queries: list[PlannedQuery] = []
    for name in _names(brand):
        queries.extend(_search_queries(name))

    ads = _ads_query(brand)
    if ads is not None:
        queries.append(ads)

    display_name = brand.display_name
    queries.append(_maps_query(display_name))
    queries.append(_local_query(display_name))
    return queries
