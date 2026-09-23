"""Scout's tools: the definitions Claude sees, and the Python that runs when it calls them.

- web_search runs on Anthropic's servers (a "server tool"). We only declare it.
- fetch_page and save_person run here, in our code (a "client tool").
"""

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

import db

MAX_PAGE_CHARS = 12_000  # about 3,000 tokens; caps what one page costs us
MAX_LINKS = 60
USER_AGENT = "Mozilla/5.0 (compatible; ScoutResearchBot/0.1)"


@dataclass
class RunState:
    """Everything one run has seen so far. The guardrails check against this."""

    run_id: str
    conn: object
    pages: dict = field(default_factory=dict)  # url -> lowercased page text (for email checks)
    seen_urls: set = field(default_factory=set)  # normalized URLs from fetched pages + search results
    people: list = field(default_factory=list)


# ---------- Tool definitions (what Claude sees) ----------

def web_search_tool(model_key):
    # Haiku 4.5 only supports the older web search version; Sonnet 5 and Opus 5.5 get the newer one.
    version = "web_search_20250305" if model_key == "haiku" else "web_search_20260209"
    return {"type": version, "name": "web_search", "max_uses": 10}  # per API call; the $ limit is the real cap


FETCH_PAGE = {
    "name": "fetch_page",
    "description": (
        "Download a web page and return its visible text, the links on it, and any emails it publishes. "
        "Use it to read team pages, bios, and announcements found through web_search. "
        "It can't run search engines; use web_search to search."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Full http(s) URL to fetch."}},
        "required": ["url"],
    },
}

SAVE_PERSON = {
    "name": "save_person",
    "description": (
        "Save one person who fits the target, as soon as you have one solid source. Every claim must come from "
        "a page you saw this run. Leave out email, linkedin_url, or x_url if you didn't find them; never guess. "
        "Calling it again for the same person adds newly found contact info and hooks."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "role": {"type": "string", "description": "Current title, e.g. 'Strategy & Operations Lead'."},
            "firm": {"type": "string", "description": "Current company or firm."},
            "why_fit": {"type": "string", "description": "One or two sentences of evidence for how they match the target."},
            "background": {
                "type": "string",
                "description": "One line on their path and style, e.g. 'ex-BCG consultant, joined Sierra 2025, "
                               "posts often on X about ops'. Only what sources show.",
            },
            "hooks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 specific, sourced facts worth mentioning in outreach: a post, talk, "
                               "investment, launch, past employer, school. Put the source URL in parentheses.",
            },
            "source_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs you fetched or saw in search results that support why_fit.",
            },
            "email": {"type": "string", "description": "Only if written on a page you fetched."},
            "linkedin_url": {"type": "string"},
            "x_url": {"type": "string"},
        },
        "required": ["name", "role", "firm", "why_fit", "background", "hooks", "source_urls"],
    },
}

CLIENT_TOOLS = [FETCH_PAGE, SAVE_PERSON]


# ---------- Helpers ----------

def normalize_url(url):
    """Make URLs comparable: drop scheme, 'www.', query, fragment, trailing slash, case."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return f"{host}{parsed.path.rstrip('/')}".lower()


def is_public_http_url(url):
    """Only fetch normal public websites, never localhost or private network addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname
    if host == "localhost" or host.endswith((".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a domain name, not a raw IP


def is_search_engine(url):
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host in {"google.com", "bing.com", "duckduckgo.com", "html.duckduckgo.com", "search.yahoo.com"}


def record_search_results(block, state):
    """Remember every URL a web search returned, so save_person can accept them as sources.

    Returns the error code if the search failed, otherwise None.
    """
    if not isinstance(block.content, list):  # a list means success; an error comes back as a single object
        return getattr(block.content, "error_code", "unknown_error")
    for result in block.content:
        url = getattr(result, "url", None)
        if url:
            state.seen_urls.add(normalize_url(url))
    return None


# ---------- Client tools (our code) ----------

def fetch_page(url, state):
    if not is_public_http_url(url):
        return f"Refused: {url} is not a public http(s) URL.", True
    if is_search_engine(url):
        return "Refused: fetch_page can't run search engines. Use the web_search tool instead.", True
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
    except httpx.HTTPError as e:
        return f"Could not fetch {url}: {e}", True
    if "html" not in response.headers.get("content-type", "") and "text" not in response.headers.get("content-type", ""):
        return f"{url} is not a web page ({response.headers.get('content-type')}).", True

    final_url = str(response.url)
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    links, emails = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            emails.add(href[7:].split("?")[0].strip())
            continue
        absolute = urljoin(final_url, href)
        if absolute.startswith("http"):
            state.seen_urls.add(normalize_url(absolute))
            links.append(f"{a.get_text(' ', strip=True)[:60]} -> {absolute}")

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    emails.update(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text))

    # Keep the full text for verification; only a truncated copy goes back to Claude.
    full = (text + " " + " ".join(emails)).lower()
    for u in (url, final_url):
        state.pages[normalize_url(u)] = full
        state.seen_urls.add(normalize_url(u))

    shown = text[:MAX_PAGE_CHARS] + (" [truncated]" if len(text) > MAX_PAGE_CHARS else "")
    parts = [f"URL: {final_url}", f"TEXT: {shown}"]
    if emails:
        parts.append("EMAILS ON PAGE: " + ", ".join(sorted(emails)))
    if links:
        parts.append("LINKS:\n" + "\n".join(dict.fromkeys(links[:MAX_LINKS])))
    return "\n\n".join(parts), False


def save_person(data, state):
    required = ["name", "role", "firm", "why_fit", "background"]
    missing = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        return f"Rejected: missing {', '.join(missing)}.", True

    # Guardrail 1: sources are required, and must be pages this run actually saw.
    hooks = [h.strip() for h in data.get("hooks") or [] if str(h).strip()]
    if not hooks:
        return "Rejected: add at least one sourced hook.", True
    sources = [u for u in data.get("source_urls") or [] if is_public_http_url(u)]
    if not sources:
        return "Rejected: at least one http(s) source URL is required.", True
    if not any(normalize_url(u) in state.seen_urls for u in sources):
        return ("Rejected: none of these source URLs came from a search result or fetched page in this run. "
                "Only cite pages you actually saw."), True

    notes = []

    # Guardrail 2: an email must appear word-for-word on a page fetched this run.
    email = (data.get("email") or "").strip()
    if email and not any(email.lower() in page for page in state.pages.values()):
        notes.append(f"email '{email}' was not found on any fetched page, stored as 'not found'")
        email = ""

    # Same idea for profile links: only keep ones this run has seen.
    profiles = {}
    for field_name in ("linkedin_url", "x_url"):
        value = (data.get(field_name) or "").strip()
        if value and normalize_url(value) not in state.seen_urls:
            notes.append(f"{field_name} '{value}' was never seen this run, stored as 'not found'")
            value = ""
        profiles[field_name] = value or "not found"

    person = {
        "name": data["name"].strip(),
        "role": data["role"].strip(),
        "firm": data["firm"].strip(),
        "why_fit": data["why_fit"].strip(),
        "email": email or "not found",
        **profiles,
        "background": data["background"].strip(),
        "hooks": hooks,
        "source_urls": sources,
    }
    key = (person["name"].lower(), person["firm"].lower())
    existing = next((p for p in state.people if (p["name"].lower(), p["firm"].lower()) == key), None)
    if existing:
        # Same person again: keep the first record, but fill in contact info that's now verified.
        added = [f for f in ("email", "linkedin_url", "x_url")
                 if existing[f] == "not found" and person[f] != "not found"]
        for f in added:
            existing[f] = person[f]
        new_sources = [u for u in sources if u not in existing["source_urls"]]
        existing["source_urls"] += new_sources
        new_hooks = [h for h in hooks if h not in existing["hooks"]]
        existing["hooks"] += new_hooks
        if new_hooks:
            added.append("hooks")
        if not added and not new_sources:
            message = f"Already saved {person['name']}; nothing new to add."
        else:
            db.update_person(state.conn, state.run_id, existing)
            message = f"Updated {person['name']}: added {', '.join(added) or 'sources'}."
    else:
        db.save_person(state.conn, state.run_id, person)
        state.people.append(person)
        message = f"Saved {person['name']} ({len(state.people)} people so far)."
    if notes:
        message += " Note: " + "; ".join(notes) + "."
    return message, False


def run_client_tool(name, tool_input, state):
    """Dispatch a tool_use block to our Python function. Returns (result_text, is_error)."""
    if name == "fetch_page":
        return fetch_page(tool_input.get("url", ""), state)
    if name == "save_person":
        return save_person(tool_input, state)
    return f"Unknown tool: {name}", True
