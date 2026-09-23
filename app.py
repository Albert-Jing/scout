"""Streamlit web UI. Run locally with: streamlit run app.py"""

import hmac
import os

import pandas as pd
import streamlit as st

from agent import MAX_COST, run_scout
from pricing import MODELS

st.set_page_config(page_title="Scout", page_icon="🔎", layout="wide")


def load_secrets():
    """On Streamlit Cloud, keys live in st.secrets. Locally they come from .env instead."""
    try:
        for key in ("ANTHROPIC_API_KEY", "APP_PASSWORD"):
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
st.caption("Give it a target; it returns sourced people, public contact channels, and a drafted opener.")

target = st.text_area("Target", placeholder="Seed VCs in SF who led AI dev-tools rounds this year")
col1, col2 = st.columns(2)
model_key = col1.selectbox("Model", list(MODELS), format_func=lambda k: f"{k} ({MODELS[k]['id']})")
max_cost = col2.number_input("Dollar limit for this run", 0.05, MAX_COST, 0.50, step=0.05)

if st.button("Run Scout", type="primary", disabled=not target.strip()):
    cost_box = st.empty()
    status = st.status("Scout is working...", expanded=True)

    def on_event(event):
        status.write(event["text"])  # the live log: every turn, search, fetch, and save
        cost_box.metric("Cost so far", f"${event['cost']:.4f}")

    result = run_scout(target.strip(), model_key, max_cost=max_cost, on_event=on_event)
    status.update(label=f"Done: {result.stop_reason}", state="complete", expanded=False)
    st.session_state.result = result  # keep it when the page reruns (e.g. after clicking download)

result = st.session_state.get("result")
if result:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("People", len(result.people))
    c2.metric("Run cost", f"${result.cost:.4f}")
    c3.metric("Turns", result.turns)
    c4.metric("Searches", result.totals["searches"])
    st.caption(
        f"Tokens: {result.totals['input']:,} input, {result.totals['cache_write']:,} cache writes, "
        f"{result.totals['cache_read']:,} cache reads, {result.totals['output']:,} output"
    )
    if result.summary:
        st.info(result.summary)
    if result.people:
        df = pd.DataFrame(result.people)
        df["source_urls"] = df["source_urls"].apply(" ".join)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Download CSV", df.to_csv(index=False), f"scout-{result.run_id}.csv", "text/csv")
