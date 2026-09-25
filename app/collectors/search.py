"""Google Search collector.

Collects four SERP surfaces from one `google` response:
  organic_results   -> is_ad=False, position = the result's real rank
  ads               -> is_ad=True,  position = the ad's real rank
  answer_box        -> is_ad=False, position from the item when it has one,
                       otherwise None (an answer box has no organic rank)
  related_questions -> only items with type == "featured_snippet": real testing
                       confirmed this is where genuine phone numbers surface
                       ("call our toll-free number ..."). Items with
                       type == "ai_overview" carry no usable contact data and
                       are skipped, as is any other related_questions type.
"""

from __future__ import annotations

from app.collectors.common import (
    SearchClient,
    as_opt_str,
    as_str,
    build_evidence,
    dict_items,
    fetch_payload,
    ranked_position,
)
from app.models import Evidence, PlannedQuery

FEATURED_SNIPPET_TYPE = "featured_snippet"


def _organic_evidence(query: PlannedQuery, payload: dict) -> list[Evidence]:
    return [
        build_evidence(
            engine=query.engine,
            query=query.query_text,
            is_ad=False,
            position=ranked_position(item, index),
            title=as_str(item.get("title")),
            link=as_opt_str(item.get("link")),
            snippet=as_opt_str(item.get("snippet")),
            raw=item,
        )
        for index, item in enumerate(dict_items(payload.get("organic_results")))
    ]


def _ads_evidence(query: PlannedQuery, payload: dict) -> list[Evidence]:
    return [
        build_evidence(
            engine=query.engine,
            query=query.query_text,
            is_ad=True,
            position=ranked_position(item, index),
            title=as_str(item.get("title")),
            link=as_opt_str(item.get("link")),
            snippet=as_opt_str(item.get("snippet")),
            raw=item,
        )
        for index, item in enumerate(dict_items(payload.get("ads")))
    ]


def _answer_box_evidence(query: PlannedQuery, payload: dict) -> list[Evidence]:
    evidence = []
    for box in dict_items(payload.get("answer_box")):
        position = box.get("position")
        evidence.append(
            build_evidence(
                engine=query.engine,
                query=query.query_text,
                is_ad=False,
                position=position if isinstance(position, int) and not isinstance(position, bool) else None,
                title=as_str(box.get("title")),
                link=as_opt_str(box.get("link")),
                snippet=as_opt_str(box.get("answer")) or as_opt_str(box.get("snippet")),
                raw=box,
            )
        )
    return evidence


def _related_question_evidence(query: PlannedQuery, payload: dict) -> list[Evidence]:
    evidence = []
    for item in dict_items(payload.get("related_questions")):
        if item.get("type") != FEATURED_SNIPPET_TYPE:
            continue
        evidence.append(
            build_evidence(
                engine=query.engine,
                query=query.query_text,
                is_ad=False,
                position=None,
                title=as_str(item.get("title")),
                link=as_opt_str(item.get("link")),
                snippet=as_opt_str(item.get("snippet")),
                raw=item,
            )
        )
    return evidence


def collect_search(client: SearchClient, queries: list[PlannedQuery]) -> list[Evidence]:
    """Parse organic results, ads, the answer box and featured-snippet
    related questions for every google_search query."""
    evidence: list[Evidence] = []
    for query in queries:
        payload = fetch_payload(client, query)
        evidence.extend(_organic_evidence(query, payload))
        evidence.extend(_ads_evidence(query, payload))
        evidence.extend(_answer_box_evidence(query, payload))
        evidence.extend(_related_question_evidence(query, payload))
    return evidence
