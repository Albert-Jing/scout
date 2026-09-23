"""The agent loop: ask Claude, run the tools it asks for, send the results back, repeat."""

import uuid
from dataclasses import dataclass
from datetime import date

import anthropic
from dotenv import load_dotenv

import db
from pricing import MODELS, turn_cost
from prompts import SYSTEM_PROMPT
from tools import CLIENT_TOOLS, RunState, record_search_results, run_client_tool, web_search_tool

load_dotenv()  # puts ANTHROPIC_API_KEY from .env into the environment, where the SDK looks for it

MAX_TURNS = 25
MAX_COST = 1.00


@dataclass
class RunResult:
    run_id: str
    people: list
    cost: float
    turns: int
    stop_reason: str
    summary: str
    totals: dict
    model_id: str
    pages_fetched: int


def run_scout(target, model_key="haiku", max_turns=MAX_TURNS, max_cost=MAX_COST,
              use_cache=True, on_event=None):
    model = MODELS[model_key]
    client = anthropic.Anthropic()
    conn = db.connect()
    state = RunState(run_id=uuid.uuid4().hex[:8], conn=conn)
    tools = [web_search_tool(model_key), *CLIENT_TOOLS]

    totals = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0, "searches": 0, "dollars": 0.0}
    turns, pages_fetched, summary, stop_reason = 0, 0, "", "finished"

    def emit(text):
        if on_event:
            on_event({"text": text, "cost": totals["dollars"]})
        else:
            print(text)

    # The whole conversation. It grows every turn and is re-sent in full every turn.
    messages = [{"role": "user", "content": f"Today's date is {date.today():%B %d, %Y}.\n\nTarget: {target}"}]

    while True:
        # Guardrail: stop at the turn limit or the dollar limit, whichever comes first.
        if turns >= max_turns:
            stop_reason = f"turn limit ({max_turns})"
            break
        if totals["dollars"] >= max_cost:
            stop_reason = f"cost limit (${max_cost:.2f})"
            break

        request = {
            "model": model["id"],
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "tools": tools,
            "messages": messages,
        }
        if use_cache:
            # Caches everything up to the latest message, so next turn re-reads it at ~10% of the price.
            request["cache_control"] = {"type": "ephemeral"}
        if model["effort"]:
            request["output_config"] = {"effort": model["effort"]}

        try:
            response = client.messages.create(**request)
        except anthropic.APIError as e:
            stop_reason = f"API error: {e}"
            break
        turns += 1

        cost = turn_cost(response.usage, model_key)
        for k in totals:
            totals[k] += cost[k]
        emit(f"Turn {turns}: {cost['input']:,} new in, {cost['cache_write']:,} cache write, "
             f"{cost['cache_read']:,} cache read, {cost['output']:,} out, {cost['searches']} searches "
             f"= ${cost['dollars']:.4f} (run total ${totals['dollars']:.4f})")

        # Append Claude's full reply (text, tool calls, search results) to the history.
        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "text" and block.text.strip():
                emit(f"Claude: {block.text.strip()[:300]}")
            elif block.type == "server_tool_use" and block.name == "web_search":
                emit(f"Search: {block.input.get('query')}")
            elif block.type == "web_search_tool_result":
                error = record_search_results(block, state)
                if error:
                    emit(f"Search failed: {error}")

        if response.stop_reason == "pause_turn":
            continue  # Anthropic's server-side search loop paused; re-send and it resumes.
        if response.stop_reason != "tool_use":
            # Search citations split the reply into many text blocks; glue them back together.
            summary = "".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason != "end_turn":
                stop_reason = f"model stopped: {response.stop_reason}"
            break

        # Claude asked for our tools. Run each one and send all results back in one user message.
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "fetch_page":
                pages_fetched += 1
                emit(f"Fetch: {block.input.get('url')}")
            result_text, is_error = run_client_tool(block.name, block.input, state)
            if block.name == "save_person" or is_error:
                emit(("Error: " if is_error else "") + result_text.splitlines()[0][:300])
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": result_text, "is_error": is_error})

        # Tell Claude where it stands, so it saves people before the budget runs out instead of researching forever.
        spent = totals["dollars"]
        note = (f"[Scout status: turn {turns} of {max_turns}, ${spent:.2f} of ${max_cost:.2f} spent, "
                f"{len(state.people)} people saved.]")
        if spent >= 0.6 * max_cost or turns >= 0.6 * max_turns:
            note += " Budget is running low: save everyone you already have evidence for now, then finish."
        results.append({"type": "text", "text": note})
        messages.append({"role": "user", "content": results})

    db.save_run(conn, state.run_id, target, model_key, turns, totals["dollars"], stop_reason)
    conn.close()
    emit(f"Stopped: {stop_reason}. {len(state.people)} people, ${totals['dollars']:.4f}.")
    return RunResult(state.run_id, state.people, totals["dollars"], turns, stop_reason, summary, totals,
                     model["id"], pages_fetched)
