"""
Confluence page updater for bot feedback corrections.

Flow:
  1. fetch_page()               — retrieve current content + version
  2. generate_updated_content() — ask Gemini to apply the correction
  3. make_slack_diff()          — produce a unified diff for display in Slack
  4. apply_update()             — write the new version back to Confluence
"""

import re
import difflib
from html.parser import HTMLParser

from atlassian import Confluence

from slack_bot.config import config


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return "\n".join(p.strip() for p in self._parts if p.strip())


def _strip_html(html: str) -> str:
    html = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", html, flags=re.DOTALL)
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


def _get_confluence() -> Confluence:
    return Confluence(
        url=config.confluence_url,
        username=config.jira_email,
        password=config.jira_api_token,
        cloud=True,
    )


def fetch_page(page_id: str) -> dict:
    """Fetch a Confluence page. Returns {title, version, html, text}."""
    confluence = _get_confluence()
    page = confluence.get_page_by_id(page_id, expand="body.storage,version")
    html = page.get("body", {}).get("storage", {}).get("value", "")
    return {
        "title": page["title"],
        "version": page["version"]["number"],
        "html": html,
        "text": _strip_html(html),
    }


def generate_updated_content(
    page_title: str,
    current_html: str,
    current_text: str,
    correction: str,
    vertex_client,
) -> tuple[str, str]:
    """Ask Gemini to apply a correction to a Confluence page. Returns (updated_html, updated_text)."""
    prompt = (
        f'You are editing a Confluence page titled "{page_title}".\n\n'
        f"A user has flagged the following correction:\n{correction}\n\n"
        f"Current page content (plain text — for reference only):\n{current_text}\n\n"
        f"Current page content (Confluence storage format XHTML):\n{current_html}\n\n"
        "Instructions:\n"
        "- Make ONLY the minimal change needed to apply the correction.\n"
        "- Do not rewrite or restructure any section that is not affected.\n"
        "- Return the COMPLETE updated page in Confluence storage format (XHTML).\n"
        "- Return ONLY the XHTML — no explanation, no markdown fencing."
    )

    updated_html = vertex_client.get_ai_response(
        prompt,
        use_slack_formatting=False,
        system_instruction=(
            "You are a precise Confluence page editor. "
            "Return only valid Confluence storage format XHTML. No explanations."
        ),
    )

    updated_html = re.sub(r"^```(?:xml|html|confluence)?\s*", "", updated_html.strip())
    updated_html = re.sub(r"\s*```$", "", updated_html)

    return updated_html, _strip_html(updated_html)


def make_slack_diff(old_text: str, new_text: str, page_title: str) -> str:
    """Return a unified diff of the plain-text content, formatted for a Slack code block."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"{page_title} (current)",
            tofile=f"{page_title} (proposed)",
            n=2,
        )
    )

    if not diff:
        return "_(No textual changes detected — the content may already be correct.)_"

    diff_text = "".join(diff)
    if len(diff_text) > 2800:
        diff_text = diff_text[:2800] + "\n… (truncated)"

    return f"```{diff_text}```"


def apply_update(
    page_id: str,
    title: str,
    version: int,
    new_html: str,
    correction_summary: str,
) -> str:
    """Write the corrected content to Confluence. Returns the page URL."""
    confluence = _get_confluence()
    confluence.update_page(
        page_id=page_id,
        title=title,
        body=new_html,
        version_number=version + 1,
        minor_edit=False,
        version_comment=f"Bot feedback: {correction_summary[:120]}",
    )
    return f"{config.confluence_url}/wiki/spaces/LOGCPL/pages/{page_id}"
