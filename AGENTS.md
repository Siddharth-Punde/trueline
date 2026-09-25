# AGENTS.md

This file contains instructions for AI agents working on this repository.

## Project Policy

- Never fetch real SerpApi results in this repo except through app/serpapi_client.py.
- Never write real phone numbers, real people's names, or a real SerpApi key into any committed file. Use data/brands/*.json for brand config and .env (gitignored) for the key.
- Every "finding" the tool reports must carry a non-empty evidence_ids list pointing to stored raw SERP items. Never let an LLM invent a finding with no evidence.
- Prefer small, testable functions. Every module in app/ gets a matching test in tests/ before we consider it done.
- Default to demo/replay mode (SERPAPI_MODE=replay) unless SERPAPI_MODE=live is explicitly set.