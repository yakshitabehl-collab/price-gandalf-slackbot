"""
BigQuery logger for Price Gandalf Q&A interactions.

Writes one row per bot response to:
  logistics-customer-staging.price_gandalf.qa_logs
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_PROJECT = "logistics-customer-staging"
_DATASET = "price_gandalf"
_TABLE = "qa_logs"
_TABLE_REF = f"{_PROJECT}.{_DATASET}.{_TABLE}"

_SCHEMA = [
    {"name": "logged_at",     "type": "TIMESTAMP", "mode": "REQUIRED"},
    {"name": "question",      "type": "STRING",    "mode": "REQUIRED"},
    {"name": "answer",        "type": "STRING",    "mode": "REQUIRED"},
    {"name": "user_id",       "type": "STRING",    "mode": "NULLABLE"},
    {"name": "channel_id",    "type": "STRING",    "mode": "NULLABLE"},
    {"name": "request_type",  "type": "STRING",    "mode": "NULLABLE"},
    {"name": "thread_ts",     "type": "STRING",    "mode": "NULLABLE"},
    {"name": "sources_cited", "type": "STRING",    "mode": "REPEATED"},
]

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account

        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
        try:
            creds_info = json.loads(creds_path)
        except (json.JSONDecodeError, TypeError):
            with open(creds_path) as f:
                creds_info = json.load(f)

        credentials = service_account.Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        _client = bigquery.Client(project=_PROJECT, credentials=credentials)
        _ensure_table(_client)
    except Exception as e:
        logger.warning(f"BQ logger init failed (Q&A logging disabled): {e}")
        _client = None

    return _client


def _ensure_table(client):
    from google.cloud import bigquery
    from google.api_core.exceptions import NotFound

    try:
        client.get_dataset(_DATASET)
    except NotFound:
        client.create_dataset(bigquery.Dataset(f"{_PROJECT}.{_DATASET}"))
        logger.info(f"Created BQ dataset {_PROJECT}.{_DATASET}")

    try:
        client.get_table(_TABLE_REF)
    except NotFound:
        schema = [bigquery.SchemaField(f["name"], f["type"], mode=f["mode"]) for f in _SCHEMA]
        table = bigquery.Table(_TABLE_REF, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(field="logged_at")
        client.create_table(table)
        logger.info(f"Created BQ table {_TABLE_REF}")


def log_qa(
    question: str,
    answer: str,
    user_id: str = None,
    channel_id: str = None,
    request_type: str = None,
    thread_ts: str = None,
    sources_cited: list[str] = None,
):
    threading.Thread(
        target=_write_row,
        args=(question, answer, user_id, channel_id, request_type, thread_ts, sources_cited or []),
        daemon=True,
    ).start()


def _write_row(question, answer, user_id, channel_id, request_type, thread_ts, sources_cited):
    try:
        client = _get_client()
        if client is None:
            return
        row = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "answer": answer,
            "user_id": user_id,
            "channel_id": channel_id,
            "request_type": request_type,
            "thread_ts": thread_ts,
            "sources_cited": sources_cited,
        }
        errors = client.insert_rows_json(_TABLE_REF, [row])
        if errors:
            logger.warning(f"BQ insert errors: {errors}")
        else:
            logger.info(f"📝 Logged Q&A to BQ ({request_type}, {len(answer)} chars)")
    except Exception as e:
        logger.warning(f"BQ log_qa failed: {e}")
