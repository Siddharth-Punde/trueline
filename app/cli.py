"""Terminal entrypoint for TrueLine.

    python -m app.cli list-brands
    python -m app.cli scan <brand_id>

`scan` runs exactly the same flow as POST /scan (app.api.scan_brand), then
prints the trust score and a findings table. SERPAPI_MODE in the env decides
replay vs live here too; nothing on the command line can opt into live.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.api import list_brands, make_client, scan_brand
from app.models import Finding, ScanResult
from app.serpapi_client import FixtureMissingError

KIND_WIDTH = 24
VALUE_WIDTH = 32
CONF_WIDTH = 6
COUNT_WIDTH = 6


def format_findings_table(findings: list[Finding]) -> str:
    """Fixed-width table: one row per finding, explanation last."""
    if not findings:
        return "No findings: every surfaced value matched the brand's official info."
    header = (
        f"{'#':>2}  {'KIND':<{KIND_WIDTH}} {'VALUE':<{VALUE_WIDTH}} "
        f"{'CONF':>{CONF_WIDTH}} {'EV':>{COUNT_WIDTH}}  EXPLANATION"
    )
    rows = [header, "-" * len(header)]
    for index, finding in enumerate(findings, start=1):
        rows.append(
            f"{index:>2}  {finding.kind.value:<{KIND_WIDTH}} {finding.value:<{VALUE_WIDTH}} "
            f"{finding.confidence:>{CONF_WIDTH}.2f} {len(finding.evidence_ids):>{COUNT_WIDTH}}  "
            f"{finding.explanation}"
        )
    return "\n".join(rows)


def format_scan_result(result: ScanResult, *, mode: str) -> str:
    lines = [
        f"Brand      : {result.brand_id}",
        f"Scanned at : {result.scanned_at.isoformat()}",
        f"Mode       : {mode}",
        f"Evidence   : {len(result.evidence)} item(s)",
        f"Trust score: {result.trust_score}/100",
        "",
        f"Findings ({len(result.findings)}):",
        format_findings_table(result.findings),
    ]
    return "\n".join(lines)


def format_brand_list() -> str:
    brands = list_brands()
    if not brands:
        return "No brand configs found in data/brands/."
    width = max(len(brand.brand_id) for brand in brands)
    lines = [f"{'BRAND_ID':<{width}}  DISPLAY_NAME"]
    lines += [f"{brand.brand_id:<{width}}  {brand.display_name}" for brand in brands]
    return "\n".join(lines)


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        client = make_client()
    except ValueError as exc:  # bad SERPAPI_MODE in the env
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        result = scan_brand(args.brand_id, client=client)
    except FixtureMissingError as exc:  # must precede FileNotFoundError (it subclasses it)
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_scan_result(result, mode=client.mode))
    return 0


def cmd_list_brands(_args: argparse.Namespace) -> int:
    print(format_brand_list())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="TrueLine CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="run a scan and print trust score + findings")
    scan_parser.add_argument("brand_id", help="brand config filename stem in data/brands/")
    scan_parser.set_defaults(func=cmd_scan)

    list_parser = subparsers.add_parser("list-brands", help="list available brand configs")
    list_parser.set_defaults(func=cmd_list_brands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
