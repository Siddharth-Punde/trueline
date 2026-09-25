"""Shared plumbing for the engine collectors.

Everything here is pure: no network, no fixture I/O. The only side effect a
collector performs is one client.search() call per planned query, and the
real SerpApiClient serves that from data/fixtures/ in replay mode.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from app.models import EngineType, Evidence, PlannedQuery


class SearchClient(Protocol):
    """Duck type satisfied by SerpApiClient (and by test fakes)."""

    def search(self, engine: str, params: dict[str, Any]) -> dict[str, Any]: ...


def fetch_payload(client: SearchClient, query: PlannedQuery) -> dict[str, Any]:
    """Run one planned query; anything that is not a dict counts as empty."""
    payload = client.search(query.engine.value, query.params)
    return payload if isinstance(payload, dict) else {}


def make_evidence_id(
    engine: EngineType | str, query: str, position: int | None, title: str
) -> str:
    """Stable sha256 over (engine, query, position, title).

    JSON encoding keeps the four fields unambiguous (a query containing a
    comma can never collide with a title) and serializes position=None as
    null, so the same real-world result hashes identically on every run.
    """
    engine_value = engine.value if isinstance(engine, EngineType) else str(engine)
    canonical = json.dumps(
        [engine_value, query, position, title],
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_evidence(
    *,
    engine: EngineType,
    query: str,
    is_ad: bool,
    position: int | None,
    title: str,
    link: str | None,
    snippet: str | None,
    raw: dict[str, Any],
) -> Evidence:
    """Evidence whose id is derived only from (engine, query, position, title)."""
    return Evidence(
        evidence_id=make_evidence_id(engine, query, position, title),
        engine=engine,
        query=query,
        is_ad=is_ad,
        position=position,
        title=title,
        link=link,
        snippet=snippet,
        raw=raw,
    )


def as_str(value: Any) -> str:
    """Evidence.title must be a str (pydantic rejects None / int)."""
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def as_opt_str(value: Any) -> str | None:
    """Optional text field: keep real strings, drop anything else."""
    return value if isinstance(value, str) else None


def ranked_position(item: dict[str, Any], index: int) -> int:
    """The item's own rank when present, else its 1-based place in the list."""
    position = item.get("position")
    if isinstance(position, int) and not isinstance(position, bool):
        return position
    return index + 1


def dict_items(value: Any) -> list[dict[str, Any]]:
    """Normalize a payload field that may be a list of items, a single item, or absent."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []
