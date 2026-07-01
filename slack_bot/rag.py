"""
RAG (Retrieval-Augmented Generation) module.

Loads the ChromaDB vector index from GCS (preferred) or the bundled fallback,
and performs semantic search against channel history.

Build / refresh the index manually:
    python data/fetch_conversations.py
    python data/create_embeddings.py
"""

import json
import logging
import os
import pathlib
import shutil
import threading
from datetime import datetime, timezone
from typing import Optional

import chromadb
from dotenv import load_dotenv
from google import genai
from google.oauth2 import service_account

load_dotenv()

logger = logging.getLogger(__name__)

COLLECTION_NAME = "slack_history"
EMBEDDING_MODEL = "text-embedding-005"

GCS_BUCKET = os.getenv("GCS_RAG_BUCKET", "")
GCS_PREFIX = "chroma_db/"

_CHROMA_DIR_TMP = "/tmp/price_gandalf_chroma_db"
_CHROMA_DIR_BUNDLED = os.path.join(os.path.dirname(__file__), "embeddings", "chroma_db")

_GCS_CHECK_INTERVAL = 24 * 3600


def _load_credentials():
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    try:
        info = json.loads(creds_path)
    except (json.JSONDecodeError, TypeError):
        with open(creds_path) as f:
            info = json.load(f)
    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )


class RAGClient:
    def __init__(self):
        self._collection = None
        self._gemini = None
        self._lock = threading.Lock()
        self._last_download: Optional[datetime] = None
        self._load()
        self._schedule_gcs_check()

    def _load(self):
        chroma_dir = self._download_from_gcs() if GCS_BUCKET else None
        if chroma_dir is None:
            chroma_dir = _CHROMA_DIR_BUNDLED

        if not os.path.exists(chroma_dir):
            logger.info("RAG index not found — run data/create_embeddings.py to build it")
            return

        try:
            chroma = chromadb.PersistentClient(path=chroma_dir)
            collection = chroma.get_collection(COLLECTION_NAME)
            logger.info(f"RAG index loaded: {collection.count()} chunks from {chroma_dir}")
        except Exception as e:
            logger.warning(f"Could not load ChromaDB collection: {e}")
            return

        try:
            gemini = self._init_gemini()
        except Exception as e:
            logger.warning(f"Could not init Gemini for RAG: {e}")
            return

        with self._lock:
            self._collection = collection
            self._gemini = gemini

    def _reload(self, chroma_dir: str):
        try:
            chroma = chromadb.PersistentClient(path=chroma_dir)
            collection = chroma.get_collection(COLLECTION_NAME)
            with self._lock:
                self._collection = collection
            logger.info(f"RAG reloaded: {collection.count()} chunks")
        except Exception as e:
            logger.warning(f"RAG reload failed: {e}")

    @staticmethod
    def _init_gemini():
        credentials = _load_credentials()
        return genai.Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
            credentials=credentials,
        )

    def _download_from_gcs(self) -> Optional[str]:
        try:
            from google.cloud import storage
            credentials = _load_credentials()
            client = storage.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"), credentials=credentials)
            bucket = client.bucket(GCS_BUCKET)
            blobs = list(bucket.list_blobs(prefix=GCS_PREFIX))
            if not blobs:
                return None

            staging = _CHROMA_DIR_TMP + "_staging"
            if os.path.exists(staging):
                shutil.rmtree(staging)
            os.makedirs(staging, exist_ok=True)

            for blob in blobs:
                relative = blob.name[len(GCS_PREFIX):]
                if not relative:
                    continue
                dest = pathlib.Path(staging) / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                blob.download_to_filename(str(dest))

            if os.path.exists(_CHROMA_DIR_TMP):
                shutil.rmtree(_CHROMA_DIR_TMP)
            shutil.move(staging, _CHROMA_DIR_TMP)

            self._last_download = datetime.now(timezone.utc)
            logger.info(f"Downloaded {len(blobs)} files from gs://{GCS_BUCKET}/{GCS_PREFIX}")
            return _CHROMA_DIR_TMP
        except Exception as e:
            logger.warning(f"GCS download failed: {e}")
            return None

    def _gcs_has_updates(self) -> bool:
        if self._last_download is None:
            return True
        try:
            from google.cloud import storage
            credentials = _load_credentials()
            client = storage.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"), credentials=credentials)
            bucket = client.bucket(GCS_BUCKET)
            for blob in bucket.list_blobs(prefix=GCS_PREFIX):
                if blob.updated and blob.updated > self._last_download:
                    return True
            return False
        except Exception as e:
            logger.warning(f"GCS update check failed: {e}")
            return False

    def _schedule_gcs_check(self):
        if not GCS_BUCKET:
            return
        t = threading.Timer(_GCS_CHECK_INTERVAL, self._run_scheduled_check)
        t.daemon = True
        t.start()

    def _run_scheduled_check(self):
        try:
            if self._gcs_has_updates():
                new_dir = self._download_from_gcs()
                if new_dir:
                    self._reload(new_dir)
        except Exception as e:
            logger.warning(f"RAG scheduled check failed: {e}")
        finally:
            self._schedule_gcs_check()

    def is_available(self) -> bool:
        return self._collection is not None and self._gemini is not None

    def search(self, query: str, n_results: int = 5) -> list:
        if not self.is_available():
            return []
        try:
            result = self._gemini.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=query,
            )
            query_embedding = result.embeddings[0].values
            with self._lock:
                n = min(n_results, self._collection.count())
                results = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n,
                )
            return results.get("documents", [[]])[0]
        except Exception as e:
            logger.warning(f"RAG search error: {e}")
            return []


try:
    rag_client = RAGClient()
except Exception as e:
    logger.warning(f"Could not initialize RAG client: {e}")
    rag_client = None
