# TrueLine

TrueLine takes a brand name plus its verified official domain(s) and phone number(s), runs "customer care" style search queries through SerpApi across Google Search, Maps/Local, and Ads Transparency, and flags anything shown to a customer that does NOT match the brand's official info — with every flag linked back to the exact search result that produced it.

## Setup

```bash
git clone <repo-url>
cd <repo-dir>
pip install -r requirements.txt
cp .env.example .env
```

Replay mode works out of the box with **zero API key** — the bundled fixtures in `data/fixtures/` are pre-recorded SERP responses, so the demo runs offline. Only set `SERPAPI_KEY` in `.env` if you want to try live mode (`SERPAPI_MODE=live`).

```bash
uvicorn app.api:app --reload
```

Then open [web/index.html](web/index.html) in your browser (the web UI makes CORS requests to `http://localhost:8000`), or just visit `http://localhost:8000` (the API serves the same page).

## Demo brands

Two brands are meant to be shown side by side — one real, one synthetic:

| `brand_id` | Display name | What it demonstrates |
| --- | --- | --- |
| `airindia` | Air India | **Real brand — authentic live-search noise.** A verified brand whose scan scores 65/100 with 12 findings — a sister-brand domain (`airindiaexpress.com`), unlisted phone numbers and off-domain links — not impersonation. Proof the tool works on real messy data, not a scripted clean result. |
| `demobrand` | QuivoKart | **Synthetic brand — clear impersonation catch.** A fake e-commerce brand whose fixtures contain a lookalike ad domain (`quivo-kart.com`), a rogue Maps listing and unofficial phone numbers, so the scan comes back with Suspected findings you can safely show on camera. |

Exact commands (both run in replay mode, offline):

```bash
python -m app.cli scan airindia     # brand_id: airindia
python -m app.cli scan demobrand    # brand_id: demobrand
```

In the web UI dropdown, pick **Air India** (`airindia`) or **QuivoKart** (`demobrand`), then press `Scan <brand name>`.

## SerpApi products used and why

- **Google Search** — The core engine. Searches for `{name} customer care number`, `{name} refund`, `{name} complaint number`, and `{name} toll free number` (with India geo params). Parses organic results, ads, answer boxes, and critically the `related_questions` items of type `featured_snippet` — real testing confirmed genuine phone numbers surface there, not from `ai_overview` items. This is the engine most likely to surface a fake customer-care number a customer would actually dial.

- **Maps / Local** (`google_maps` and `google_local`) — Catches impersonation at the "near me / call now" layer. Searches `{name} customer care` and parses place listings, including the `unclaimed_listing` flag as a bonus trust signal. A fake listing showing an unofficial phone or domain intercepts customers who are already in a hurry to contact the brand.

- **Ads Transparency** (`google_ads_transparency_center`) — Checks whether the advertiser name behind an ad on the brand's official domain matches the brand. This is an explicitly **best-effort signal** (SPEC: "never a core dependency"); real Playground testing confirmed it returns empty for several real brands. An empty result is treated as normal, never as an error, and does not block or degrade a scan.

## Non-goals (deliberately out of scope)

- No exposed-document / subdomain dorking
- No personal data about individuals — brand-level only
- No calling flagged numbers or visiting flagged sites
- No trained ML classifier; scoring is rule-based, and an LLM may only classify ambiguous items or write summaries — never create a Finding without `evidence_ids`
- No user accounts, no database; brand configs are JSON files, results computed on demand
- No multi-language support in v1
- No automated takedowns or reporting to anyone
- v1 covers 3 brands; more brands is a stretch goal
- Ads Transparency is best-effort, not a core dependency — an empty result is normal, not a bug
- The video/report never names a real business as "scam"; only "suspected" / "unverified" wording is used, and a synthetic brand pair is preferred for anything shown on camera

## AI tools disclosure

Built using OpenCode with free models — see [AGENTS.md](../AGENTS.md) for the workflow details.
