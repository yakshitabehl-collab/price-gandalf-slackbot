"""
Fetch and cache Confluence reference pages for use as bot system context.
Pages are fetched once at startup using Jira/Confluence credentials.

Root pages and all their child pages are fetched recursively.
To add more root pages, add their IDs to _ROOT_PAGES below.
"""

import re
from html.parser import HTMLParser

from atlassian import Confluence

from slack_bot.config import config
from slack_bot.schema_catalog import get_schema_prompt


# (title, page_id, space_key) — all child pages are fetched recursively
_ROOT_PAGES = [
    ("Pricing Documentation", "36640152", "LOGCPL"),
    ("Dynamic Pricing Service", "67470918", "LOGCPL"),
    ("Pricing Domain - Customer Tribe", "36641669", "LOGCPL"),
]


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return " ".join(self._parts)


def _strip_html(html: str) -> str:
    html = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", html, flags=re.DOTALL)
    stripper = _HTMLStripper()
    stripper.feed(html)
    return re.sub(r"\s+", " ", stripper.get_text()).strip()


def _get_all_child_pages(confluence: Confluence, page_id: str, space_key: str) -> list[tuple[str, str, str]]:
    """Recursively fetch all child pages under a given page ID."""
    results = []
    start = 0
    limit = 50
    while True:
        children = confluence.get_page_child_by_type(
            page_id, type="page", start=start, limit=limit
        )
        if not children:
            break
        for child in children:
            child_id = child["id"]
            child_title = child["title"]
            results.append((child_title, child_id, space_key))
            results.extend(_get_all_child_pages(confluence, child_id, space_key))
        if len(children) < limit:
            break
        start += limit
    return results


def _fetch_page_text(confluence: Confluence, page_id: str) -> str:
    page = confluence.get_page_by_id(page_id, expand="body.storage")
    html = page.get("body", {}).get("storage", {}).get("value", "")
    return _strip_html(html)


def _fetch() -> str:
    if not config.jira_enabled:
        print("⚠️  Confluence context: credentials not configured, skipping.")
        return _base_system_prompt()

    try:
        confluence = Confluence(
            url=config.confluence_url,
            username=config.jira_email,
            password=config.jira_api_token,
            cloud=True,
        )
    except Exception as e:
        print(f"⚠️  Confluence context: failed to connect: {e}")
        return _base_system_prompt()

    # Expand root pages with all their children
    all_pages = []
    for title, page_id, space_key in _ROOT_PAGES:
        all_pages.append((title, page_id, space_key))
        try:
            children = _get_all_child_pages(confluence, page_id, space_key)
            all_pages.extend(children)
            print(f"✓ Found {len(children)} child pages under '{title}'")
        except Exception as e:
            print(f"⚠️  Could not fetch children of '{title}': {e}")

    sections = []
    for title, page_id, space_key in all_pages:
        try:
            text = _fetch_page_text(confluence, page_id)
            if text:
                sections.append((title, page_id, space_key, text))
                print(f"✓ Confluence page loaded: {title} ({len(text):,} chars)")
        except Exception as e:
            print(f"⚠️  Confluence context: failed to fetch '{title}': {e}")

    schema_section = get_schema_prompt()

    if not sections:
        return _base_system_prompt() + "\n\n" + schema_section

    pages_text = "\n\n".join(f"=== {title} ===\n{text}" for title, _, _, text in sections)

    return (
        _base_system_prompt()
        + "\n\nIMPORTANT: Before answering any question, always check the internal reference "
        "documentation below. If the answer is in the documentation, base your response "
        "on it and cite the relevant section. Only fall back to general knowledge when "
        "the topic is not covered in the documentation.\n\n"
        "When you use information from one of the documentation sections below, include "
        "a source citation using exactly this format: [SOURCE: Section Title] — where "
        "Section Title matches one of the section headers.\n\n"
        + pages_text
        + "\n\n"
        + schema_section
    )


def _base_system_prompt() -> str:
    return (
        "You are Price Gandalf, an AI assistant for the Pricing Analytics team at Delivery Hero. "
        "You help pricing team stakeholders and analysts answer questions about pricing experiments, "
        "subscription metrics, and pricing data. "
        "You are knowledgeable about BigQuery, SQL, and the Pricing team's data assets.\n\n"
        "RESPONSE STYLE:\n"
        "- Be concise. Answer in as few words as possible while still being complete.\n"
        "- Use plain Slack formatting: *bold* for key terms, bullet points for lists.\n"
        "- Do NOT use markdown headers (##, ###) — they don't render in Slack.\n"
        "- Do NOT over-explain. Skip preamble like 'Great question!' or 'Here is a summary of...'.\n"
        "- If the answer is one sentence, keep it one sentence.\n"
        "- Cite sources as [SOURCE: Page Title] ONLY when quoting a Confluence documentation page "
        "listed in the sections below. Do NOT use [SOURCE: ...] for RAG results, Slack messages, "
        "DPS test names, Jira tickets, or any other data — just incorporate that information naturally.\n\n"
        "UNCERTAINTY RULE:\n"
        "- If you are not confident about your answer — the topic is not covered in the documentation "
        "and you are guessing or speculating — output the single token [UNSURE] on the very first line "
        "of your response, then give your best attempt anyway. Do NOT say [UNSURE] if you are confident. "
        "Do NOT hallucinate facts you are unsure about without flagging it."
    )


confluence_system_prompt: str = _fetch()

def _build_page_maps():
    if not config.jira_enabled:
        return {}, {}
    try:
        confluence = Confluence(
            url=config.confluence_url,
            username=config.jira_email,
            password=config.jira_api_token,
            cloud=True,
        )
        all_pages = []
        for title, page_id, space_key in _ROOT_PAGES:
            all_pages.append((title, page_id, space_key))
            all_pages.extend(_get_all_child_pages(confluence, page_id, space_key))
        links = {
            title: f"{config.confluence_url}/wiki/spaces/{space_key}/pages/{page_id}"
            for title, page_id, space_key in all_pages
        }
        ids = {title: page_id for title, page_id, space_key in all_pages}
        return links, ids
    except Exception:
        return {}, {}


confluence_page_links: dict
confluence_page_ids: dict
confluence_page_links, confluence_page_ids = _build_page_maps()
