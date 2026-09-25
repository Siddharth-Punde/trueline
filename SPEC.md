# TrueLine — Project Spec

## One-line pitch
TrueLine takes a brand name plus its verified official domain(s) and phone number(s), runs "customer care" style search queries through SerpApi across Google Search, Maps/Local, and Ads Transparency, and flags anything shown to a customer that does NOT match the brand's official info — with every flag linked back to the exact search result that produced it.

## Hackathon fit
- Event: SerpApi India Hackathon 2026, deadline Oct 5 2026 23:59 IST.
- Track: Knowledge & Public Interest (SerpApi may reassign).
- Judging angle: idea strength (real fraud pattern — fake "customer care" numbers found via search), originality (a customer-facing audit, not a company-facing recon scan), meaningful SerpApi usage (every finding traces to a SERP item across 3+ engines), technical complexity (multi-engine collection + evidence provenance + rule-based scoring, not one bolted-on API call).

## Non-goals (deliberately cut — do not expand scope here without a good reason)
- No exposed-document / subdomain dorking.
- No personal data about individuals — brand-level only.
- No calling flagged numbers or visiting flagged sites.
- No trained ML classifier. Scoring is rule-based; an LLM may only classify ambiguous items or write summaries, and can never create a Finding without evidence_ids.
- No user accounts, no database. Brand configs are JSON files; results are computed on demand.
- No multi-language support in v1.
- No automated takedowns or reporting to anyone.
- v1 covers 3 brands. More brands is a stretch goal, not a requirement.
- Ads Transparency (domain lookup) is best-effort, not a core dependency — confirmed via real Playground tests that it returns empty for multiple real brands. Never let it block or error out a scan; treat an empty result as normal, not a bug.
- The video/report never names a real business as "scam" — confirmed real testing surfaced an actual unrelated, low-rated business for an ambiguous query. Use "suspected" / "unverified" wording always, and prefer a synthetic brand pair for anything shown on camera.

## Data contract
Implement exactly these models in app/models.py (Pydantic v2):

- Brand: id, display_name, official_domains (list[str]), official_phones (list[str], E.164), aliases (list[str], default [])
- PlannedQuery: engine (str), query_text (str), params (dict)
- Evidence: evidence_id (str, stable hash of engine+query+position+title), engine (str: "google_search" | "google_maps" | "google_local" | "ads_transparency"), query (str), is_ad (bool), position (int | None), title (str), link (str | None), snippet (str | None), raw (dict, the untouched original SerpApi item). Note: for "google_search", Evidence also comes from `related_questions` items where `"type": "featured_snippet"` (real testing confirmed this is where genuine phone numbers surface) — NOT from `"type": "ai_overview"` items, those carry no usable phone/domain text and should be skipped. For "google_maps", also read `raw["unclaimed_listing"]` when present (bool) — an unclaimed listing is a bonus trust signal, feed it into scoring later.
- Finding: finding_id (str), kind (str: "unofficial_phone" | "unofficial_domain" | "ad_off_domain" | "advertiser_mismatch" | "maps_listing_mismatch"), value (str), evidence_ids (list[str], never empty), confidence (float, 0-1), explanation (str)
- ScanResult: brand_id (str), scanned_at (datetime), trust_score (int, 0-100), findings (list[Finding]), evidence (list[Evidence])

## Query templates (used by query_planner.py)
Per brand (and each alias): "{name} customer care number", "{name} customer care", "{name} refund", "{name} complaint number", "{name} toll free number". Use India geo params (gl=in, hl=en). One Ads Transparency lookup keyed on official_domains[0]. One Maps/Local query per brand using "{name} customer care".

## Scoring rubric (must stay simple and explainable, not fancy)
trust_score starts at 100. Subtract weighted amounts per Finding based on severity: an unofficial phone/domain in an AD or top-3 organic position is the most severe; a maps/local mismatch is next; a lower-ranked organic mention is least severe. Document the exact weights you choose as a comment in verify.py. Clamp to [0, 100].

## Modes
- SERPAPI_MODE=replay (default): reads from data/fixtures/, never touches the network.
- SERPAPI_MODE=live: calls the real SerpApi, and always saves the raw response to data/fixtures/ afterward.

## Demo flow (what the video will show)
1. Open the web UI, pick a brand.
2. Run scan (replay mode against pre-recorded fixtures, so the demo is fast and reproducible).
3. Show trust score + flagged findings + linked evidence.
4. Open the HTML report.