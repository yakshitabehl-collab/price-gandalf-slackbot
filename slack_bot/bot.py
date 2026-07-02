"""
Main Slack bot implementation using Socket Mode.
"""

import os
import re
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bot.config import config
from slack_bot.vertex_ai import vertex_client
from slack_bot.jira_client import jira_client
from slack_bot.rag import rag_client
from slack_bot.confluence_context import confluence_system_prompt, confluence_page_links, confluence_page_ids
from slack_bot.confluence_updater import fetch_page, generate_updated_content, make_slack_diff, apply_update
from slack_bot.bq_logger import log_qa
from slack_bot.channel_utils import (
    fetch_channel_messages,
    format_messages_for_summary,
    create_summary_prompt,
    fetch_thread_messages,
    format_thread_for_context,
    parse_channel_reference,
    lookup_channel_by_name,
    get_channel_name,
)

combined_system_prompt: str = confluence_system_prompt
_doc_links: dict = confluence_page_links
_pending_corrections: dict = {}

app = App(token=config.slack_bot_token)


def get_thread_context(client, channel_id: str, thread_ts: str, bot_user_id: str) -> str:
    if not thread_ts:
        return ""
    thread_messages = fetch_thread_messages(client, channel_id, thread_ts)
    if not thread_messages or len(thread_messages) <= 1:
        return ""
    return format_thread_for_context(thread_messages[:-1], client, bot_user_id)


def build_rag_context(query: str) -> str:
    if not rag_client or not rag_client.is_available():
        return ""
    chunks = rag_client.search(query, n_results=5)
    if not chunks:
        return ""
    joined = "\n\n---\n\n".join(chunks)
    return (
        "Relevant past messages from the pricing channel that may help answer the question:\n\n"
        + joined
        + "\n\n---\n\n"
    )


def _cited_page_ids(text: str) -> list[tuple[str, str]]:
    found = []
    seen = set()
    for pattern in (r"<[^|>]+\|([^>]+)>", r"\[SOURCE:\s*([^\]]+)\]"):
        for title in re.findall(pattern, text):
            title = title.strip()
            if title in confluence_page_ids and title not in seen:
                found.append((title, confluence_page_ids[title]))
                seen.add(title)
    return found


def _handle_fix(text: str, thread_ts: str, channel_id: str, user_id: str, bot_user_id: str, say, client):
    if user_id not in config.feedback_users:
        say(text="⛔ You don't have permission to submit corrections.", thread_ts=thread_ts)
        return

    correction = text[len("fix:"):].strip()
    if not correction:
        say(
            text="Please include the correction after `fix:`, e.g.\n`fix: The experiment ran for 2 weeks, not 1`",
            thread_ts=thread_ts,
        )
        return

    try:
        replies = client.conversations_replies(channel=channel_id, ts=thread_ts)
        bot_messages = [m for m in replies.get("messages", []) if m.get("user") == bot_user_id]
    except Exception as e:
        say(text=f"⚠️ Could not fetch thread history: {e}", thread_ts=thread_ts)
        return

    cited = []
    seen = set()
    for msg in bot_messages:
        for title, page_id in _cited_page_ids(msg.get("text", "")):
            if title not in seen:
                cited.append((title, page_id))
                seen.add(title)

    if not cited:
        page_list = "\n".join(f"• {t}" for t in confluence_page_ids)
        say(
            text=(
                "⚠️ I couldn't find a Confluence source citation in this thread.\n"
                f"Which page should be corrected? Options:\n{page_list}"
            ),
            thread_ts=thread_ts,
        )
        return

    if len(cited) > 1:
        page_list = "\n".join(f"- {t}" for t, _ in cited)
        pick_prompt = (
            f"The user wants to correct: {correction}\n\n"
            f"The bot cited these Confluence pages:\n{page_list}\n\n"
            "Which single page is most likely the source of the incorrect information? "
            "Reply with the exact page title only, nothing else."
        )
        picked_title = vertex_client.get_ai_response(pick_prompt, use_slack_formatting=False).strip().strip('"')
        page_match = next(((t, pid) for t, pid in cited if t == picked_title), cited[0])
    else:
        page_match = cited[0]

    page_title, page_id = page_match
    say(text=f"⏳ Fetching _{page_title}_ and generating the correction…", thread_ts=thread_ts)

    try:
        page_data = fetch_page(page_id)
        new_html, new_text = generate_updated_content(
            page_title=page_title,
            current_html=page_data["html"],
            current_text=page_data["text"],
            correction=correction,
            vertex_client=vertex_client,
        )
        diff = make_slack_diff(page_data["text"], new_text, page_title)
    except Exception as e:
        say(text=f"⚠️ Error generating correction: {e}", thread_ts=thread_ts)
        return

    _pending_corrections[thread_ts] = {
        "page_id": page_id,
        "page_title": page_title,
        "version": page_data["version"],
        "new_html": new_html,
        "correction": correction,
    }

    say(
        text=(
            f"*Proposed edit to _{page_title}_:*\n\n"
            f"{diff}\n\n"
            "Reply `confirm` to apply this change, or `cancel` to discard."
        ),
        thread_ts=thread_ts,
    )


def _handle_confirm(thread_ts: str, user_id: str, say):
    if user_id not in config.feedback_users:
        say(text="⛔ You don't have permission to apply corrections.", thread_ts=thread_ts)
        return
    pending = _pending_corrections.get(thread_ts)
    if not pending:
        say(text="⚠️ No pending correction found for this thread.", thread_ts=thread_ts)
        return
    try:
        url = apply_update(
            page_id=pending["page_id"],
            title=pending["page_title"],
            version=pending["version"],
            new_html=pending["new_html"],
            correction_summary=pending["correction"],
        )
        del _pending_corrections[thread_ts]
        say(text=f"✅ *{pending['page_title']}* updated on Confluence: <{url}|View page>", thread_ts=thread_ts)
    except Exception as e:
        say(text=f"⚠️ Failed to update Confluence: {e}", thread_ts=thread_ts)


def _handle_cancel(thread_ts: str, user_id: str, say):
    if user_id not in config.feedback_users:
        say(text="⛔ You don't have permission to cancel corrections.", thread_ts=thread_ts)
        return
    if thread_ts in _pending_corrections:
        del _pending_corrections[thread_ts]
        say(text="❌ Correction discarded.", thread_ts=thread_ts)
    else:
        say(text="⚠️ No pending correction to cancel.", thread_ts=thread_ts)


def _inject_doc_links(response: str) -> str:
    # Regex handles titles that may themselves contain brackets, e.g. [CHOICE] SG|...
    _SOURCE_RE = re.compile(r'\[SOURCE:\s*((?:[^\[\]]+|\[[^\]]*\])*)\]')

    def _replace_marker(match):
        title = match.group(1).strip()
        url = _doc_links.get(title)
        if url:
            return f"<{url}|{title}>"
        # Title not found in Confluence — strip the [SOURCE: ...] wrapper so it
        # doesn't show as confusing raw brackets. Keep the title inline.
        return title

    response = _SOURCE_RE.sub(_replace_marker, response)
    for title, url in _doc_links.items():
        link = f"<{url}|{title}>"
        response = re.sub(r'(?<!\|)' + re.escape(title), link, response)
    return response


def _format_group_tag(raw: str) -> str:
    """Convert a group handle or subteam ID to the correct Slack mention format."""
    if not raw:
        return ""
    raw = raw.strip().lstrip("@")
    if raw.startswith("<!"):
        return f" {raw}"
    if raw.startswith("S") and len(raw) > 5:
        # Proper Slack subteam ID — produces a real ping
        return f" <!subteam^{raw}|{raw}>"
    # Plain handle — visible but won't ping; good enough as a breadcrumb
    return f" @{raw}"


def _handle_uncertainty(response: str) -> str:
    """
    If the AI flagged uncertainty with [UNSURE], wrap the response with a
    humorous escalation message and tag the analytics group if configured.
    """
    if not response.lstrip().startswith("[UNSURE]"):
        return response
    clean = re.sub(r"^\[UNSURE\]\s*\n?", "", response.lstrip(), count=1).strip()
    tag = _format_group_tag(config.escalation_group)
    header = f"🔮 *My crystal ball is a little foggy here. Summoning higher authority.*{tag}\n\n"
    footer = "\n\n_If I got this wrong, reply `fix: [correction]` and I'll update the docs._"
    return header + clean + footer


def detect_jira_intent(message: str) -> bool:
    jira_keywords = ["jira", "ticket", "epic", "sprint"]
    if re.search(r'\b[A-Z]{2,10}-\d+\b', message):
        return True
    return any(kw in message.lower() for kw in jira_keywords)


def parse_jira_intent_with_ai(message: str, conversation_context: str = "") -> dict:
    context_section = f"\n\nPrevious conversation:\n{conversation_context}\n" if conversation_context else ""
    system_prompt = f"""You are a Jira intent parser. Analyze the user's message and extract the Jira operation.
{context_section}
Return ONLY a JSON object (no markdown) with this structure:
{{
    "action": "search" | "get" | "create" | "unknown",
    "parameters": {{
        "jql": "JQL query string",
        "issue_key": "PROJ-123",
        "project": "PROJECT_KEY",
        "summary": "Issue summary",
        "description": "Issue description",
        "issue_type": "Task" | "Bug" | "Story" | "Epic",
        "priority": "High" | "Medium" | "Low" | null,
        "assignee": "username" | null
    }},
    "confidence": "high" | "medium" | "low"
}}

Guidelines:
- For search: Convert natural language to JQL
- For get: Extract the issue key
- For create: Use CLOGBI as the default project if none specified
- Use "unknown" if you can't determine the intent

User message: {message}"""

    try:
        ai_response = vertex_client.get_ai_response(system_prompt, max_tokens=1000)
        cleaned = ai_response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        return json.loads(cleaned)
    except Exception as e:
        print(f"⚠️  Error parsing Jira intent: {e}")
        return {"action": "unknown", "parameters": {}, "confidence": "low"}


def handle_jira_request(message: str, conversation_context: str = "") -> str:
    if not jira_client.is_enabled():
        return (
            "⚠️ *Jira integration is not configured.*\n\n"
            "Add these to your `.env` file:\n"
            "```\nJIRA_URL=https://deliveryhero.atlassian.net\n"
            "JIRA_EMAIL=your-email@deliveryhero.com\nJIRA_API_TOKEN=your-api-token\n```"
        )

    intent = parse_jira_intent_with_ai(message, conversation_context)
    action = intent.get("action")
    params = intent.get("parameters", {})
    confidence = intent.get("confidence", "low")

    if confidence == "low" or action == "unknown":
        return None

    if action == "search":
        jql = params.get("jql", "")
        if not jql:
            return "❌ Could not generate a search query. Please try rephrasing."
        return jira_client.format_search_results(jira_client.search_issues(jql, max_results=10))

    elif action == "get":
        issue_key = params.get("issue_key", "")
        if not issue_key:
            return "❌ Could not identify the issue key. Please specify it like 'CLOGBI-123'."
        return jira_client.format_issue_detail(jira_client.get_issue(issue_key))

    elif action == "create":
        summary = params.get("summary", "")
        if not summary:
            return "❌ Could not determine what issue to create. Please provide a summary."
        return jira_client.format_create_result(jira_client.create_issue(
            summary=summary,
            project=params.get("project"),
            issue_type=params.get("issue_type", "Task"),
            description=params.get("description"),
            priority=params.get("priority"),
            assignee=params.get("assignee"),
        ))

    return "❌ Unknown Jira operation. Please try again."


@app.event("app_mention")
def handle_mention(event, say, client):
    try:
        bot_info = client.auth_test()
        bot_user_id = bot_info["user_id"]

        text = event.get("text", "")
        message = re.sub(f"<@{bot_user_id}>", "", text).strip()

        if not message:
            say(text="Hi! Please include a message with your mention.", thread_ts=event.get("thread_ts") or event.get("ts"))
            return

        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        user_id = event.get("user")

        msg_lower = message.lower().strip()
        if msg_lower.startswith("fix:"):
            _handle_fix(message, thread_ts, channel_id, user_id, bot_user_id, say, client)
            return
        if msg_lower in ("confirm", "confirm.", "confirm!"):
            _handle_confirm(thread_ts, user_id, say)
            return
        if msg_lower in ("cancel", "cancel.", "cancel!"):
            _handle_cancel(thread_ts, user_id, say)
            return

        conversation_context = get_thread_context(client, channel_id, thread_ts, bot_user_id)

        if detect_jira_intent(message):
            jira_response = handle_jira_request(message, conversation_context)
            if jira_response is not None:
                say(text=jira_response, thread_ts=thread_ts)
                log_qa(question=message, answer=jira_response, user_id=user_id,
                       channel_id=channel_id, request_type="mention", thread_ts=thread_ts)
                return

        if "summarize" in message.lower() or "summary" in message.lower():
            days = 7
            day_match = re.search(r'(\d+)\s*days?', message.lower())
            if day_match:
                days = min(int(day_match.group(1)), 30)

            channel_ref = parse_channel_reference(message)
            if channel_ref:
                target_channel_id = (
                    channel_ref if re.match(r'^C[A-Z0-9]{8,}$', channel_ref)
                    else lookup_channel_by_name(client, channel_ref)
                )
                if not target_channel_id:
                    say(
                        text=f"❌ Could not find channel `#{channel_ref}`. Make sure I'm invited and the name is correct.",
                        thread_ts=thread_ts,
                    )
                    return
            else:
                target_channel_id = channel_id

            channel_display_name = get_channel_name(client, target_channel_id)
            try:
                messages = fetch_channel_messages(client, target_channel_id, days=days)
                if not messages:
                    say(text=f"No messages found in {channel_display_name} for the last {days} days.", thread_ts=thread_ts)
                    return
                messages_text = format_messages_for_summary(messages, client)
                prompt = create_summary_prompt(messages_text, days)
                response = vertex_client.get_ai_response(prompt, max_tokens=4096, system_instruction=combined_system_prompt)
                response = f"📊 *Summary of {channel_display_name}* (last {days} days, {len(messages)} messages)\n\n{response}"
            except Exception as e:
                error_msg = str(e)
                if "not_in_channel" in error_msg or "channel_not_found" in error_msg:
                    response = f"❌ I don't have access to {channel_display_name}. Please invite me with `/invite @{bot_info['user']}`"
                else:
                    response = f"Sorry, I encountered an error creating the summary: {error_msg}"
        else:
            rag_context = build_rag_context(message)
            prompt_parts = []
            if rag_context:
                prompt_parts.append(rag_context)
            if conversation_context:
                prompt_parts.append(f"Previous conversation:\n{conversation_context}")
            prompt_parts.append(f"Current message: {message}")
            if len(prompt_parts) > 1:
                prompt_parts.append("Please respond considering the context above.")
            response = vertex_client.get_ai_response("\n\n".join(prompt_parts), system_instruction=combined_system_prompt)
            response = _inject_doc_links(response)
            response = _handle_uncertainty(response)

        say(text=response, thread_ts=thread_ts)
        log_qa(question=message, answer=response, user_id=user_id,
               channel_id=channel_id, request_type="mention", thread_ts=thread_ts,
               sources_cited=[t for t, _ in _cited_page_ids(response)])

    except Exception as e:
        try:
            say(text=f"Sorry, I encountered an error: {str(e)}", thread_ts=event.get("thread_ts") or event.get("ts"))
        except Exception:
            pass


@app.event("message")
def handle_message(event, say, client):
    if event.get("bot_id") or event.get("subtype"):
        return

    channel_type = event.get("channel_type")

    if channel_type == "im":
        text = event.get("text", "").strip()
        if not text:
            return

        try:
            bot_info = client.auth_test()
            bot_user_id = bot_info["user_id"]

            channel_id = event.get("channel")
            thread_ts = event.get("thread_ts")
            conversation_context = ""
            if thread_ts:
                conversation_context = get_thread_context(client, channel_id, thread_ts, bot_user_id)

            if detect_jira_intent(text):
                jira_response = handle_jira_request(text, conversation_context)
                if jira_response is not None:
                    say(text=jira_response)
                    log_qa(question=text, answer=jira_response, user_id=event.get("user"),
                           channel_id=channel_id, request_type="dm", thread_ts=thread_ts)
                    return

            if "summarize" in text.lower() or "summary" in text.lower():
                days = 7
                day_match = re.search(r'(\d+)\s*days?', text.lower())
                if day_match:
                    days = min(int(day_match.group(1)), 30)

                channel_ref = parse_channel_reference(text)
                if not channel_ref:
                    say(text="Please specify which channel to summarize. Example:\n`summarize #pricing-data last 7 days`")
                    return

                target_channel_id = (
                    channel_ref if re.match(r'^C[A-Z0-9]{8,}$', channel_ref)
                    else lookup_channel_by_name(client, channel_ref)
                )
                if not target_channel_id:
                    say(text=f"❌ Could not find channel `#{channel_ref}`.")
                    return

                channel_display_name = get_channel_name(client, target_channel_id)
                try:
                    messages = fetch_channel_messages(client, target_channel_id, days=days)
                    if not messages:
                        say(text=f"No messages found in {channel_display_name} for the last {days} days.")
                        return
                    messages_text = format_messages_for_summary(messages, client)
                    prompt = create_summary_prompt(messages_text, days)
                    response = vertex_client.get_ai_response(prompt, max_tokens=4096, system_instruction=combined_system_prompt)
                    response = f"📊 *Summary of {channel_display_name}* (last {days} days, {len(messages)} messages)\n\n{response}"
                    say(text=response)
                    log_qa(question=text, answer=response, user_id=event.get("user"),
                           channel_id=channel_id, request_type="dm", thread_ts=thread_ts)
                    return
                except Exception as e:
                    say(text=f"Sorry, I encountered an error: {str(e)}")
                    return

            rag_context = build_rag_context(text)
            prompt_parts = []
            if rag_context:
                prompt_parts.append(rag_context)
            if conversation_context:
                prompt_parts.append(f"Previous conversation:\n{conversation_context}")
            prompt_parts.append(f"Current message: {text}")
            if len(prompt_parts) > 1:
                prompt_parts.append("Please respond considering the context above.")
            response = vertex_client.get_ai_response("\n\n".join(prompt_parts), system_instruction=combined_system_prompt)
            response = _inject_doc_links(response)
            response = _handle_uncertainty(response)

            say(text=response)
            log_qa(question=text, answer=response, user_id=event.get("user"),
                   channel_id=channel_id, request_type="dm", thread_ts=thread_ts,
                   sources_cited=[t for t, _ in _cited_page_ids(response)])

        except Exception as e:
            say(text=f"Sorry, I encountered an error: {str(e)}")

    elif channel_type in ("channel", "group"):
        channel_id = event.get("channel")
        pricing_channel_id = config.pricing_channel_id

        # Only auto-reply if a pricing channel is configured and this is it
        if not pricing_channel_id or channel_id != pricing_channel_id:
            return

        ts = event.get("ts")
        thread_ts = event.get("thread_ts")
        is_thread_reply = bool(thread_ts and thread_ts != ts)

        text = event.get("text", "").strip()
        if not text:
            return

        bot_info = client.auth_test()
        bot_user_id = bot_info["user_id"]

        if f"<@{bot_user_id}>" in text:
            return

        if is_thread_reply:
            msg_lower = text.lower().strip()
            user_id = event.get("user")
            if msg_lower.startswith("fix:"):
                _handle_fix(text, thread_ts, channel_id, user_id, bot_user_id, say, client)
                return
            if msg_lower in ("confirm", "confirm.", "confirm!"):
                _handle_confirm(thread_ts, user_id, say)
                return
            if msg_lower in ("cancel", "cancel.", "cancel!"):
                _handle_cancel(thread_ts, user_id, say)
                return
            return

        try:
            rag_context = build_rag_context(text)
            prompt_parts = []
            if rag_context:
                prompt_parts.append(rag_context)
            prompt_parts.append(f"Current message: {text}")
            if rag_context:
                prompt_parts.append("Please respond considering the context above.")
            response = vertex_client.get_ai_response("\n\n".join(prompt_parts), system_instruction=combined_system_prompt)
            response = _inject_doc_links(response)
            response = _handle_uncertainty(response)
            say(text=response, thread_ts=ts)
            log_qa(question=text, answer=response, user_id=event.get("user"),
                   channel_id=channel_id, request_type="channel_auto", thread_ts=ts,
                   sources_cited=[t for t, _ in _cited_page_ids(response)])
        except Exception as e:
            say(text=f"Sorry, I encountered an error: {str(e)}", thread_ts=ts)


def _start_health_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            pass

    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("", port), Handler).serve_forever()


def main():
    threading.Thread(target=_start_health_server, daemon=True).start()
    print("🚀 Starting Price Gandalf...")
    handler = SocketModeHandler(app, config.slack_app_token)
    print("✅ Bot is running! @mention the bot or send it a DM")
    print("🛑 Press Ctrl+C to stop\n")
    handler.start()


if __name__ == "__main__":
    main()
