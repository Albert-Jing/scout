"""Streamlit web UI. Run locally with: streamlit run app.py"""

import hmac
import os

import pandas as pd
import streamlit as st

from agent import DEFAULT_COUNT, MAX_COST, run_scout
from pricing import MODELS
from scout import flatten
from writer import draft_all, load_about_me

st.set_page_config(page_title="Scout", page_icon="🔎", layout="wide")


def load_secrets():
    """On Streamlit Cloud, keys live in st.secrets. Locally they come from .env and me.md instead."""
    try:
        for key in ("ANTHROPIC_API_KEY", "APP_PASSWORD", "ABOUT_ME"):
            if key in st.secrets and not os.environ.get(key):
                os.environ[key] = st.secrets[key]
    except Exception:
        pass  # no secrets file locally; .env (loaded by agent.py) covers it


def require_password():
    """Block everything below until the right password is entered. Runs cost real money."""
    expected = os.environ.get("APP_PASSWORD")
    if not expected:
        st.error("APP_PASSWORD is not set. Add it to .env (local) or the app's secrets (Streamlit Cloud).")
        st.stop()
    if st.session_state.get("authed"):
        return
    attempt = st.text_input("Password", type="password")
    if attempt and hmac.compare_digest(attempt, expected):
        st.session_state.authed = True
        st.rerun()
    elif attempt:
        st.error("Wrong password.")
    st.stop()


load_secrets()
require_password()

st.title("Scout")
st.caption("Describe who you want to reach. Scout finds them, verifies what it can, and drafts outreach from your notes.")

about_me = load_about_me()
if about_me:
    st.caption(f"Your notes: loaded ({len(about_me.split())} words).")
else:
    st.warning("Your notes are empty, so drafts will be generic. Fill in me.md (local) or the ABOUT_ME secret.")

target = st.text_area("Target", placeholder="Strategy and ops people at application-layer AI startups like Sierra, Decagon, Harvey")
col1, col2, col3, col4 = st.columns(4)
model_key = col1.selectbox("Research model", list(MODELS), format_func=lambda k: f"{k} ({MODELS[k]['id']})")
count = col2.number_input("People to find", 1, 25, DEFAULT_COUNT)
max_cost = col3.number_input("Research $ limit", 0.05, MAX_COST, 0.50, step=0.05)
write_drafts = col4.checkbox("Draft outreach (Sonnet)", value=True)

if st.button("Run Scout", type="primary", disabled=not target.strip()):
    cost_box = st.empty()
    status = st.status("Scout is working...", expanded=True)

    def on_event(event):
        status.write(event["text"])  # the live log: every turn, search, fetch, and save
        cost_box.metric("Research cost so far", f"${event['cost']:.4f}")

    result = run_scout(target.strip(), model_key, int(count), max_cost=max_cost, on_event=on_event)
    draft_cost = 0.0
    if write_drafts and result.people:
        status.update(label="Drafting outreach...")
        draft_cost = draft_all(result.people, result.run_id, "sonnet", on_event=status.write)
    status.update(label=f"Done: {result.stop_reason}", state="complete", expanded=False)
    st.session_state.result = result  # keep it when the page reruns (e.g. after clicking download)
    st.session_state.draft_cost = draft_cost

result = st.session_state.get("result")
if result:
    draft_cost = st.session_state.get("draft_cost", 0.0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("People", len(result.people))
    c2.metric("Total cost", f"${result.cost + draft_cost:.4f}")
    c3.metric("Research / drafts", f"${result.cost:.3f} / ${draft_cost:.3f}")
    c4.metric("Searches / pages", f"{result.totals['searches']} / {result.pages_fetched}")
    st.caption(
        f"Model {result.model_id} · {result.turns} turns · "
        f"Tokens: {result.totals['input']:,} input, {result.totals['cache_write']:,} cache writes, "
        f"{result.totals['cache_read']:,} cache reads, {result.totals['output']:,} output"
    )
    if result.summary:
        st.info("Claude's summary (unchecked; the cards below are what passed the guardrails):\n\n" + result.summary)

    for p in result.people:
        d = p.get("draft")
        header = f"{p['name']} · {p['role']}, {p['firm']}"
        if d:
            header += f" · {d['channel']} · fit: {d['fit']}"
        with st.expander(header, expanded=True):
            st.write(f"**Background:** {p['background']}")
            st.write(f"**Why they fit:** {p['why_fit']}")
            links = [f"[{label}]({url})" for label, url in
                     (("LinkedIn", p["linkedin_url"]), ("X", p["x_url"])) if url != "not found"]
            st.write(f"**Email:** {p['email']}  ·  " + ("  ·  ".join(links) or "no profiles found"))
            st.write("**Hooks:**\n" + "\n".join(f"- {h}" for h in p["hooks"]))
            if d:
                st.caption(f"Reader: {d['reader']}")
                st.caption(f"Angle: {d['angle']}")
                if d["subject"]:
                    st.code(d["subject"], language=None)
                st.code(d["message"], language=None, wrap_lines=True)  # has a copy button

    if result.people:
        df = pd.DataFrame([flatten(p) for p in result.people])
        st.download_button("Download CSV", df.to_csv(index=False), f"scout-{result.run_id}.csv", "text/csv")
