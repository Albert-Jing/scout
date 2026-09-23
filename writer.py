"""Outreach writer. Not an agent: one API call per person, no tools, no loop.

The code decides the channel (a fixed rule). Claude decides the tone and which parts of your
background to use (a judgment call), and explains both so you can check them before sending.
"""

import os
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

import db
from pricing import MODELS, turn_cost
from prompts import WRITER_PROMPT

HERE = Path(__file__).parent
ME_PATH = HERE / "me.md"
TEMPLATE_PATH = HERE / "me.example.md"


class Draft(BaseModel):
    """The exact shape Claude must return. The API enforces it (structured outputs)."""

    reader: str = Field(description="One line: what kind of reader this is, and the tone you chose.")
    angle: str = Field(description="Which parts of the sender's notes you used and why they fit this reader.")
    fit: Literal["strong", "ok", "weak"]
    subject: str = Field(description="Email subject line. Empty string for linkedin and x.")
    message: str


def load_about_me():
    """Your notes: me.md locally (gitignored), or the ABOUT_ME secret when hosted."""
    text = ME_PATH.read_text() if ME_PATH.exists() else os.environ.get("ABOUT_ME", "")
    if TEMPLATE_PATH.exists() and text.strip() == TEMPLATE_PATH.read_text().strip():
        return ""  # still the blank template
    return text.strip()


def pick_channel(person):
    """Email beats LinkedIn beats X. Returns (channel to write for, label to show)."""
    if person["email"] != "not found":
        return "email", "email"
    if person["linkedin_url"] != "not found":
        return "linkedin", "linkedin"
    if person["x_url"] != "not found":
        return "x", "x"
    return "linkedin", "none found (LinkedIn-style draft)"


def describe(person, channel):
    hooks = "\n".join(f"- {h}" for h in person["hooks"])
    return (
        f"Channel: {channel}\n\n"
        f"Recipient: {person['name']}, {person['role']} at {person['firm']}\n"
        f"Background: {person['background']}\n"
        f"Why they matched the search: {person['why_fit']}\n"
        f"Hooks:\n{hooks}"
    )


def draft_all(people, run_id, model_key="sonnet", on_event=print):
    """Write one draft per person. Adds person['draft'], saves it to the database, returns total cost."""
    about_me = load_about_me()
    if not about_me:
        on_event("Note: me.md is empty, so drafts will be generic. Fill it in for tailored messages.")

    client = anthropic.Anthropic()
    conn = db.connect()
    total = 0.0
    # Your notes are identical for every person, so they're cached: paid in full once, then ~10% after.
    system = [
        {"type": "text", "text": WRITER_PROMPT},
        {"type": "text", "text": f"<sender_notes>\n{about_me or '(empty)'}\n</sender_notes>",
         "cache_control": {"type": "ephemeral"}},
    ]

    for person in people:
        channel, label = pick_channel(person)
        try:
            response = client.messages.parse(
                model=MODELS[model_key]["id"],
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": describe(person, channel)}],
                output_format=Draft,
            )
        except anthropic.APIError as e:
            on_event(f"Draft failed for {person['name']}: {e}")
            continue
        cost = turn_cost(response.usage, model_key)["dollars"]
        total += cost
        if response.parsed_output is None:
            on_event(f"No draft for {person['name']} (stop reason: {response.stop_reason})")
            continue

        draft = {**response.parsed_output.model_dump(), "channel": label}
        if channel != "email":
            draft["subject"] = ""
        person["draft"] = draft
        db.save_draft(conn, run_id, person, draft)
        on_event(f"Drafted {label} message for {person['name']} (fit: {draft['fit']}, ${cost:.4f})")

    conn.close()
    return total
