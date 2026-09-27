from __future__ import annotations

from datetime import datetime, timezone

from app.models import Brand, Finding, ScanResult

_ENGINE_LABELS: dict[str, str] = {
    "google_search": "Google Search",
    "google_maps": "Google Maps",
    "google_local": "Local results",
    "ads_transparency": "Ads Transparency",
}

_KIND_LABELS: dict[str, str] = {
    "unofficial_phone": "Unofficial phone number",
    "unofficial_domain": "Unofficial domain",
    "ad_off_domain": "Ad points off the official domain",
    "advertiser_mismatch": "Advertiser does not match the brand",
    "maps_listing_mismatch": "Maps listing does not match",
}

_TRUST_LABEL: dict[str, str] = {
    "good": "Consistent with official details",
    "caution": "Some items need a closer look",
    "alert": "Several items do not match official details",
}


def _trust_band(score: int) -> str:
    if score >= 80:
        return "good"
    if score >= 50:
        return "caution"
    return "alert"


def _finding_row(finding: Finding, evidence_by_id: dict[str, object]) -> str:
    linked = [evidence_by_id[eid] for eid in finding.evidence_ids if eid in evidence_by_id]
    snippets = []
    for ev in linked:
        if getattr(ev, "snippet", None):
            snippets.append(getattr(ev, "snippet", ""))
        elif getattr(ev, "title", None):
            snippets.append(getattr(ev, "title", ""))
    joined_snippet = "; ".join(snippets)
    confidence_pct = int(round(finding.confidence * 100))

    engine_badge = "; ".join(
        _ENGINE_LABELS.get(getattr(ev, "engine", ""), getattr(ev, "engine", ""))
        for ev in linked
    )

    return f"""<tr>
<td class="kind">{_KIND_LABELS.get(finding.kind, finding.kind)}</td>
<td class="value">{finding.value}</td>
<td class="confidence">{confidence_pct}%</td>
<td class="snippet">{joined_snippet}</td>
<td class="engine">{engine_badge}</td>
</tr>"""


def render_html_report(result: ScanResult, brand: Brand) -> str:
    """Produce a clean, self-contained HTML report string."""
    scanned_at = (
        result.scanned_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if result.scanned_at.tzinfo is not None
        else result.scanned_at.strftime("%Y-%m-%d %H:%M UTC")
    )
    confidence_pct = int(round(result.trust_score))
    band = _trust_band(result.trust_score)
    trust_label = _TRUST_LABEL[band]
    finding_count = len(result.findings)
    evidence_count = len(result.evidence)

    evidence_by_id: dict[str, object] = {ev.evidence_id: ev for ev in result.evidence}

    rows = "\n".join(_finding_row(f, evidence_by_id) for f in result.findings) if result.findings else """<tr><td colspan="5" class="empty">No mismatches were found against the brand's official details.</td></tr>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="brand-id" content="{brand.id}">
<title>TrueLine report — {brand.display_name}</title>
<style>
  :root {{
    --bg: #f8fafc; --card: #ffffff; --text: #1e293b; --muted: #64748b;
    --border: #e2e8f0; --accent: #0f172a; --good: #16a34a;
    --caution: #ca8a04; --alert: #dc2626;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 2rem 1.5rem; }}
  header {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem; margin-bottom: 2rem; }}
  .brand-info h1 {{ font-size: 1.75rem; font-weight: 700; }}
  .brand-info p {{ color: var(--muted); font-size: 0.9rem; margin-top: 0.25rem; }}
  .score-card {{ text-align: center; border: 2px solid var(--border); border-radius: 12px; padding: 1.25rem 2rem; background: var(--card); min-width: 160px; }}
  .score {{ font-size: 3rem; font-weight: 800; line-height: 1; }}
  .score.good {{ color: var(--good); }} .score.caution {{ color: var(--caution); }} .score.alert {{ color: var(--alert); }}
  .score-label {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.25rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .summary {{ display: flex; gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap; }}
  .summary-card {{ flex: 1; min-width: 140px; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; text-align: center; }}
  .summary-card .num {{ font-size: 1.5rem; font-weight: 700; }}
  .summary-card .lbl {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
  h2 {{ font-size: 1.25rem; margin-bottom: 1rem; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }}
  th {{ background: var(--accent); color: #fff; text-align: left; padding: 0.75rem 1rem; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  td {{ padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  .kind {{ font-weight: 600; }}
  .confidence {{ font-weight: 700; }}
  .snippet {{ color: var(--muted); font-size: 0.85rem; max-width: 320px; }}
  .engine {{ font-size: 0.8rem; color: var(--muted); }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem !important; }}
  footer {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.8rem; text-align: center; }}
  @media (max-width: 640px) {{
    header {{ flex-direction: column; }}
    .summary {{ flex-direction: column; }}
    .snippet {{ max-width: 100%; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="brand-info">
      <h1>{brand.display_name}</h1>
      <p>Trust score: <strong>{confidence_pct}/100</strong> — {trust_label}</p>
    </div>
    <div class="score-card">
      <div class="score {band}">{confidence_pct}</div>
      <div class="score-label">trust score</div>
    </div>
  </header>

  <div class="summary">
    <div class="summary-card"><div class="num">{finding_count}</div><div class="lbl">Finding(s)</div></div>
    <div class="summary-card"><div class="num">{evidence_count}</div><div class="lbl">Evidence item(s)</div></div>
  </div>

  <h2>Flagged findings</h2>
  <table>
    <thead>
      <tr><th>Kind</th><th>Value</th><th>Confidence</th><th>Linked evidence snippet</th><th>Engine</th></tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>

  <footer>
    Generated by TrueLine using SerpApi — data current as of {scanned_at}
  </footer>
</div>
</body>
</html>"""
