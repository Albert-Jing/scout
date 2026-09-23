"""Command-line entry point: python scout.py "seed VCs in SF who led AI dev-tools rounds this year" """

import argparse
import csv

from agent import MAX_COST, MAX_TURNS, run_scout
from pricing import MODELS

CSV_FIELDS = ["name", "role", "firm", "why_fit", "email", "linkedin_url", "x_url", "source_urls", "opener"]


def write_csv(people, path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for p in people:
            writer.writerow({**p, "source_urls": " ".join(p["source_urls"])})


def main():
    parser = argparse.ArgumentParser(description="Scout: find and research people for outreach.")
    parser.add_argument("target", help="Who to find, in plain English.")
    parser.add_argument("--model", choices=list(MODELS), default="haiku")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    parser.add_argument("--max-cost", type=float, default=MAX_COST, help="Dollar limit for this run.")
    parser.add_argument("--no-cache", action="store_true", help="Turn off prompt caching (to compare cost).")
    parser.add_argument("--csv", help="Also write results to this CSV file.")
    args = parser.parse_args()

    result = run_scout(args.target, args.model, args.max_turns, args.max_cost, use_cache=not args.no_cache)

    print(f"\n{len(result.people)} people | {result.turns} turns | ${result.cost:.4f} | stopped: {result.stop_reason}\n")
    for p in result.people:
        print(f"- {p['name']}, {p['role']} at {p['firm']}")
        print(f"    why: {p['why_fit']}")
        print(f"    email: {p['email']} | linkedin: {p['linkedin_url']} | x: {p['x_url']}")
        print(f"    opener: {p['opener']}")
    if result.summary:
        print(f"\n{result.summary}")
    if args.csv:
        write_csv(result.people, args.csv)
        print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
