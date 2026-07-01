"""
Fetch message history from Slack channels for RAG indexing.

Usage:
    python data/fetch_conversations.py
    python data/fetch_conversations.py --days 180
    python data/fetch_conversations.py --channels log-dps-analytics pricing-data --days 90

Output: data/slack_messages.json
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "slack_messages.json")
DEFAULT_CHANNELS = ["log-dps-analytics"]
DEFAULT_DAYS = 90


def get_channel_id(client: WebClient, name: str) -> Optional[str]:
    name = name.lstrip("#")
    cursor = None
    while True:
        resp = client.conversations_list(
            types="public_channel,private_channel",
            limit=200,
            cursor=cursor,
        )
        for ch in resp.get("channels", []):
            if ch["name"] == name:
                return ch["id"]
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            return None


def fetch_messages(client: WebClient, channel_id: str, oldest_ts: float) -> list[dict]:
    messages = []
    cursor = None
    while True:
        try:
            resp = client.conversations_history(
                channel=channel_id,
                oldest=str(oldest_ts),
                limit=200,
                cursor=cursor,
            )
        except SlackApiError as e:
            print(f"  ⚠️  Error fetching messages: {e.response['error']}")
            break

        batch = resp.get("messages", [])
        messages.extend(batch)

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(0.5)

    return messages


def fetch_thread_replies(client: WebClient, channel_id: str, thread_ts: str) -> list[dict]:
    replies = []
    cursor = None
    while True:
        try:
            resp = client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                limit=200,
                cursor=cursor,
            )
        except SlackApiError:
            break

        msgs = resp.get("messages", [])
        replies.extend(msgs[1:])  # skip parent (already in main fetch)

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(0.3)

    return replies


def resolve_usernames(client: WebClient, messages: list[dict]) -> dict[str, str]:
    user_ids = {m.get("user") for m in messages if m.get("user")}
    names = {}
    for uid in user_ids:
        try:
            resp = client.users_info(user=uid)
            profile = resp["user"].get("profile", {})
            names[uid] = profile.get("display_name") or profile.get("real_name") or uid
        except SlackApiError:
            names[uid] = uid
        time.sleep(0.2)
    return names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", nargs="+", default=DEFAULT_CHANNELS)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = parser.parse_args()

    token = os.getenv("SLACK_USER_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    if not token:
        raise SystemExit("SLACK_USER_TOKEN or SLACK_BOT_TOKEN not set in .env")

    client = WebClient(token=token)
    oldest_ts = (datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp()

    all_chunks = []

    for channel_name in args.channels:
        print(f"\n📥 Fetching #{channel_name} (last {args.days} days)...")

        # If the channel name looks like an ID already, use it directly
        if channel_name.startswith("C") and channel_name.isupper():
            channel_id = channel_name
        else:
            channel_id = get_channel_id(client, channel_name)
        if not channel_id:
            print(f"  ⚠️  Channel #{channel_name} not found — skipping")
            continue

        messages = fetch_messages(client, channel_id, oldest_ts)
        print(f"  Found {len(messages)} messages")

        print("  Resolving usernames...")
        usernames = resolve_usernames(client, messages)

        threads: dict[str, list[dict]] = {}
        standalone: list[dict] = []

        for msg in messages:
            if msg.get("subtype"):
                continue
            text = msg.get("text", "").strip()
            if not text:
                continue

            ts = msg.get("ts", "")
            thread_ts = msg.get("thread_ts")
            reply_count = msg.get("reply_count", 0)
            user = usernames.get(msg.get("user", ""), "unknown")
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

            entry = {"user": user, "ts": ts, "dt": dt, "text": text}

            if thread_ts and thread_ts == ts and reply_count > 0:
                threads[ts] = [entry]
            elif thread_ts and thread_ts != ts:
                threads.setdefault(thread_ts, []).append(entry)
            else:
                standalone.append(entry)

        # Fetch thread replies
        for thread_ts in list(threads.keys()):
            print(f"  Fetching thread replies for {len(threads)} threads...", end="\r")
            replies = fetch_thread_replies(client, channel_id, thread_ts)
            for r in replies:
                text = r.get("text", "").strip()
                if not text:
                    continue
                user = usernames.get(r.get("user", ""), "unknown")
                dt = datetime.fromtimestamp(float(r["ts"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                threads[thread_ts].append({"user": user, "ts": r["ts"], "dt": dt, "text": text})
            time.sleep(0.3)

        print()

        # Build chunks: each thread = one chunk, standalone messages grouped by 10
        for ts, thread_msgs in threads.items():
            thread_msgs.sort(key=lambda m: m["ts"])
            chunk_text = "\n".join(f"[{m['dt']}] {m['user']}: {m['text']}" for m in thread_msgs)
            all_chunks.append({
                "id": f"{channel_name}_{ts}",
                "channel": channel_name,
                "type": "thread",
                "text": chunk_text,
                "ts": ts,
            })

        for i in range(0, len(standalone), 10):
            batch = standalone[i:i + 10]
            batch.sort(key=lambda m: m["ts"])
            chunk_text = "\n".join(f"[{m['dt']}] {m['user']}: {m['text']}" for m in batch)
            all_chunks.append({
                "id": f"{channel_name}_batch_{batch[0]['ts']}",
                "channel": channel_name,
                "type": "messages",
                "text": chunk_text,
                "ts": batch[0]["ts"],
            })

        print(f"  ✅ {len(threads)} threads + {len(standalone)} standalone → {len(all_chunks)} chunks so far")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_chunks, f, indent=2)

    print(f"\n✅ Saved {len(all_chunks)} chunks to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
