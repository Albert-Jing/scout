# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Scout is

A research agent: given a target (e.g. "seed VCs in SF who led AI dev-tools rounds this year"), it returns 15-25 people with name, role, firm, why they fit, source links, public contact channels, and a drafted one-line opener. 

## Commands

```bash
source .venv/bin/activate                     # Python 3.13 venv; activate in every new terminal
pip install -r requirements.txt
cp .env.example .env                          # then set ANTHROPIC_API_KEY and APP_PASSWORD

python scout.py "<target>"                    # CLI run, Haiku by default (cheap; use for testing)
python scout.py "<target>" --model sonnet --csv out.csv
python scout.py "<target>" --no-cache         # compare cost without prompt caching
streamlit run app.py                          # web UI at http://localhost:8501
```

There is no test suite yet. Tool and guardrail logic in `tools.py` can be exercised offline (no API key) by building a `RunState` with an in-memory SQLite connection and calling `fetch_page` / `save_person` directly.

## Architecture

No agent framework on purpose: the loop is hand-written so every token and tool call is visible. Don't introduce LangChain or an agent SDK.

- `agent.py` - `run_scout()` is the whole agent: call `client.messages.create` with the system prompt, tools, and the growing `messages` list; append Claude's full `response.content`; if `stop_reason == "tool_use"`, run each client tool and send all `tool_result` blocks back in one user message; if `pause_turn`, re-send unchanged; anything else ends the run. Emits progress through an `on_event` callback (the CLI prints it, the UI streams it).
- `tools.py` - tool definitions plus their Python. `web_search` is a server tool (Anthropic runs it; Haiku needs `web_search_20250305`, Sonnet 5 / Opus 5.5 use `web_search_20260209`). `fetch_page` (httpx + BeautifulSoup) and `save_person` are client tools. `RunState` records every page fetched and every URL seen in search results or page links; the guardrails check against it.
- `pricing.py` - model IDs, prices, and `turn_cost(usage)`, which prices uncached input, cache writes (1.25x), cache reads, output, and searches ($0.01 each).
- `prompts.py` - the system prompt: who counts as a fit and the contact-info rules. The owner edits this.
- `db.py` - SQLite (`scout.db`, gitignored): a `runs` table and a `people` table.
- `scout.py` - CLI. `app.py` - Streamlit UI with a password gate, a live log, a results table, CSV download, and run cost.

## Guardrails (never weaken these)

- Every run stops at 25 turns or its dollar limit (default and UI maximum: $1.00), whichever comes first.
- `save_person` rejects a person unless at least one source URL was actually fetched or returned by search in this run.
- An email is stored only if it appears verbatim on a page fetched this run; LinkedIn/X URLs only if seen this run. Otherwise the field is `"not found"`. Never guess or construct contact info, including in prompts or test data.

## Models and cost

Haiku 4.5 (`claude-haiku-4-5`, $1/$5 per MTok) for development and testing; Sonnet 5 (`claude-sonnet-5`, $2/$10) for real runs; Opus 5.5 (`claude-opus-5-5`, $4/$20) for comparison only. Sonnet and Opus run at `effort: medium`. Prompt caching is on by default through top-level `cache_control`, so each turn re-reads the earlier conversation at the cache-read price. Keep the system prompt and tool list byte-stable (no dates or run IDs in them), or caching silently stops working; the date goes in the first user message.

## Secrets and deploy

`.env` holds `ANTHROPIC_API_KEY` and `APP_PASSWORD` locally and is never committed. On Streamlit Community Cloud, the same two keys go in the app's Secrets settings; `app.py` copies them into the environment. The Cloud filesystem is temporary, so `scout.db` resets on redeploy; the CSV download is the durable output.

## Working with the owner

- Claude writes most of the code; explain every change and API call in plain language, and point to the file and line.
- Don't rewrite code the owner typed unless asked. When asked to review it, say what's wrong and why.
- One task per prompt. The owner runs the git commands and commits by hand after each working step.
