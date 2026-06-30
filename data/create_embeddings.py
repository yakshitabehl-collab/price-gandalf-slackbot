"""
Create ChromaDB vector embeddings from fetched Slack messages.

Run after fetch_conversations.py:
    python data/fetch_conversations.py
    python data/create_embeddings.py

Output: slack_bot/embeddings/chroma_db  (also uploaded to GCS if GCS_RAG_BUCKET is set)
"""

import json
import os
import shutil

import chromadb
from dotenv import load_dotenv
from google import genai
from google.oauth2 import service_account

load_dotenv()

INPUT_FILE = os.path.join(os.path.dirname(__file__), "slack_messages.json")
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "slack_bot", "embeddings", "chroma_db")
COLLECTION_NAME = "slack_history"
EMBEDDING_MODEL = "text-embedding-005"
BATCH_SIZE = 50  # Vertex AI embedding batch limit


def load_credentials():
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    try:
        info = json.loads(creds_path)
    except (json.JSONDecodeError, TypeError):
        with open(creds_path) as f:
            info = json.load(f)
    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )


def embed_texts(client: genai.Client, texts: list[str]) -> list[list[float]]:
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
    )
    return [e.values for e in result.embeddings]


def upload_to_gcs(chroma_dir: str, bucket_name: str, project: str):
    from google.cloud import storage
    credentials = load_credentials()
    gcs = storage.Client(project=project, credentials=credentials)
    bucket = gcs.bucket(bucket_name)

    uploaded = 0
    for root, _, files in os.walk(chroma_dir):
        for fname in files:
            local_path = os.path.join(root, fname)
            relative = os.path.relpath(local_path, chroma_dir)
            blob_name = f"chroma_db/{relative}"
            bucket.blob(blob_name).upload_from_filename(local_path)
            uploaded += 1

    print(f"  ✅ Uploaded {uploaded} files to gs://{bucket_name}/chroma_db/")


def main():
    if not os.path.exists(INPUT_FILE):
        raise SystemExit(f"Input file not found: {INPUT_FILE}\nRun data/fetch_conversations.py first.")

    with open(INPUT_FILE) as f:
        chunks = json.load(f)

    if not chunks:
        raise SystemExit("No chunks found in input file.")

    print(f"📂 Loaded {len(chunks)} chunks from {INPUT_FILE}")

    print("🔑 Initialising Vertex AI...")
    credentials = load_credentials()
    gemini = genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        credentials=credentials,
    )

    if os.path.exists(CHROMA_DIR):
        shutil.rmtree(CHROMA_DIR)
    os.makedirs(CHROMA_DIR, exist_ok=True)

    chroma = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = chroma.get_or_create_collection(COLLECTION_NAME)

    total = len(chunks)
    for i in range(0, total, BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        ids = [c["id"] for c in batch]
        metadatas = [{"channel": c["channel"], "type": c["type"], "ts": c["ts"]} for c in batch]

        print(f"  Embedding batch {i // BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE} ({len(batch)} chunks)...")
        embeddings = embed_texts(gemini, texts)

        collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    print(f"\n✅ ChromaDB index built: {collection.count()} chunks at {CHROMA_DIR}")

    gcs_bucket = os.getenv("GCS_RAG_BUCKET", "")
    if gcs_bucket:
        print(f"\n☁️  Uploading to GCS bucket: {gcs_bucket}...")
        upload_to_gcs(CHROMA_DIR, gcs_bucket, os.getenv("GOOGLE_CLOUD_PROJECT"))
    else:
        print("\nℹ️  GCS_RAG_BUCKET not set — skipping GCS upload (index is local only)")


if __name__ == "__main__":
    main()
