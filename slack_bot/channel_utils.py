"""
Utility functions for working with Slack channels.
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from slack_sdk import WebClient


def parse_channel_reference(text: str) -> Optional[str]:
    slack_mention = re.search(r'<#([A-Z0-9]+)(?:\|[^>]+)?>', text)
    if slack_mention:
        return slack_mention.group(1)
    channel_name = re.search(r'#([\w-]+)', text)
    if channel_name:
        return channel_name.group(1)
    channel_id = re.search(r'\b(C[A-Z0-9]{8,})\b', text)
    if channel_id:
        return channel_id.group(1)
    return None


def lookup_channel_by_name(client: WebClient, channel_name: str) -> Optional[str]:
    try:
        result = client.conversations_list(types="public_channel,private_channel", limit=1000)
        if not result["ok"]:
            return None
        for channel in result.get("channels", []):
            if channel.get("name") == channel_name.lower():
                return channel.get("id")
        return None
    except Exception as e:
        print(f"Error looking up channel by name: {e}")
        return None


def get_channel_name(client: WebClient, channel_id: str) -> str:
    try:
        result = client.conversations_info(channel=channel_id)
        if result["ok"]:
            return f"#{result['channel']['name']}"
        return channel_id
    except Exception:
        return channel_id


def fetch_channel_messages(
    client: WebClient,
    channel_id: str,
    days: int = 7,
    limit: int = 1000,
) -> List[Dict]:
    cutoff_time = datetime.now() - timedelta(days=days)
    oldest_ts = cutoff_time.timestamp()
    messages = []
    cursor = None

    try:
        while len(messages) < limit:
            response = client.conversations_history(
                channel=channel_id,
                oldest=str(oldest_ts),
                limit=min(200, limit - len(messages)),
                cursor=cursor,
            )
            if not response["ok"]:
                break
            messages.extend(response.get("messages", []))
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        user_messages = [
            msg for msg in messages
            if msg.get("type") == "message" and not msg.get("bot_id") and msg.get("text")
        ]
        user_messages.sort(key=lambda x: float(x.get("ts", 0)))
        return user_messages
    except Exception as e:
        print(f"Error in fetch_channel_messages: {e}")
        return []


def format_messages_for_summary(
    messages: List[Dict],
    client: WebClient,
    max_messages: int = 500,
) -> str:
    if not messages:
        return "No messages found in the specified time period."

    if len(messages) > max_messages:
        messages = messages[-max_messages:]

    user_cache = {}
    lines = []
    for msg in messages:
        user_id = msg.get("user", "Unknown")
        if user_id not in user_cache:
            try:
                info = client.users_info(user=user_id)
                user_cache[user_id] = (
                    info["user"].get("real_name") or info["user"].get("name", "Unknown")
                    if info["ok"] else "Unknown"
                )
            except Exception:
                user_cache[user_id] = "Unknown"
        lines.append(f"[{user_cache[user_id]}]: {msg.get('text', '')}")

    return "\n".join(lines)


def create_summary_prompt(messages_text: str, days: int) -> str:
    return f"""Please provide a concise summary of the following Slack channel conversation from the last {days} days.

Include:
1. Main topics discussed
2. Key decisions or action items
3. Important questions or concerns raised
4. Notable participants

Channel messages:
{messages_text}

Format your response for Slack:
- Use *bold* for emphasis
- Use • for bullet points
- Do NOT use ## headers — use *Section Name* instead
- Keep it concise and well-organized"""


def fetch_thread_messages(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
) -> List[Dict]:
    try:
        response = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=1000)
        if not response["ok"]:
            return []
        return response.get("messages", [])
    except Exception as e:
        print(f"Error in fetch_thread_messages: {e}")
        return []


def format_thread_for_context(
    messages: List[Dict],
    client: WebClient,
    bot_user_id: str,
) -> str:
    if not messages:
        return ""

    user_cache = {}
    lines = []
    for msg in messages:
        text = msg.get("text", "")
        if not text:
            continue
        user_id = msg.get("user", msg.get("bot_id", "Unknown"))
        if user_id == bot_user_id or msg.get("bot_id"):
            lines.append(f"Assistant: {text}")
        else:
            if user_id not in user_cache:
                try:
                    info = client.users_info(user=user_id)
                    user_cache[user_id] = (
                        info["user"].get("real_name") or info["user"].get("name", "User")
                        if info["ok"] else "User"
                    )
                except Exception:
                    user_cache[user_id] = "User"
            lines.append(f"{user_cache[user_id]}: {text}")

    return "\n".join(lines)
