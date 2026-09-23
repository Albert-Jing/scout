"""Command-line entry point: python scout.py "strategy and ops people at Sierra, Decagon, Harvey" """

import argparse
import csv

from agent import DEFAULT_COUNT, MAX_COST, MAX_TURNS, run_scout
from pricing import MODELS
from writer import draft_all

CSV_FIELDS = ["name", "role", "firm", "why_fit", "background", "hooks", "email", "linkedin_url", "x_url",
              "source_urls", "channel", "fit", "reader", "angle", "subject", "message"]


def flatten(person):
    """One CSV row: lists joined into text, draft fields pulled up to the top level."""
    return {
        **person,
        **person.get("draft", {}),
        "hooks": " | ".join(person["hooks"]),
        "source_urls": " ".join(person["source_urls"]),
    }


def write_csv(people, path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for p in people:
            writer.writerow(flatten(p))


def main():
    parser = argparse.ArgumentParser(description="Scout: find people and draft outreach to them.")
    parser.add_argument("target", help="Who to find, in plain English.")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="How many people to find.")
    parser.add_argument("--model", choices=list(MODELS), default="haiku", help="Model for research.")
    parser.add_argument("--writer-model", choices=list(MODELS), default="sonnet", help="Model for drafts.")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    parser.add_argument("--max-cost", type=float, default=MAX_COST, help="Dollar limit for research.")
    parser.add_argument("--no-cache", action="store_true", help="Turn off prompt caching (to compare cost).")
    parser.add_argument("--no-drafts", action="store_true", help="Research only; skip outreach drafts.")
    parser.add_argument("--csv", help="Also write results to this CSV file.")
    args = parser.parse_args()

    result = run_scout(args.target, args.model, args.count, args.max_turns, args.max_cost,
                       use_cache=not args.no_cache)
    draft_cost = 0.0
    if result.people and not args.no_drafts:
        draft_cost = draft_all(result.people, result.run_id, args.writer_model)

    t = result.totals
    print(f"\n{len(result.people)} people | model {result.model_id} | {result.turns} turns | "
          f"{t['searches']} searches | {result.pages_fetched} pages fetched | stopped: {result.stop_reason}")
    print(f"Tokens: {t['input']:,} new input, {t['cache_write']:,} cache writes, "
          f"{t['cache_read']:,} cache reads, {t['output']:,} output")
    print(f"Cost: ${result.cost:.4f} research + ${draft_cost:.4f} drafts = ${result.cost + draft_cost:.4f}\n")

    for p in result.people:
        print(f"=== {p['name']}, {p['role']} at {p['firm']}")
        print(f"    background: {p['background']}")
        print(f"    email: {p['email']} | linkedin: {p['linkedin_url']} | x: {p['x_url']}")
        for hook in p["hooks"]:
            print(f"    hook: {hook}")
        d = p.get("draft")
        if d:
            print(f"    --- {d['channel']} draft (fit: {d['fit']}) ---")
            print(f"    reader: {d['reader']}")
            print(f"    angle: {d['angle']}")
            if d["subject"]:
                print(f"    subject: {d['subject']}")
            print("    " + d["message"].replace("\n", "\n    "))
        print()
    if result.summary:
        print(f"Claude's summary (unchecked; the list above is what passed the guardrails):\n{result.summary}")
    if args.csv:
        write_csv(result.people, args.csv)
        print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
