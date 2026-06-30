# Price Gandalf — Slack AI Bot for Pricing Analytics

An AI-powered Slack bot for the Pricing Analytics team at Delivery Hero. Ask it questions about pricing experiments, subscription metrics, and pricing data — it answers using internal Confluence documentation, past Slack discussions, and knowledge of all Pricing BigQuery tables.

Inspired by [Choice Gandalf](https://github.com/deliveryhero/choice-gandalf-slackbot) built by the Choice Analytics team.

---

## What it does

- **Auto-replies** to messages in the designated pricing Slack channel
- **Answers @mentions and DMs** from any channel
- **Checks Confluence docs first** — reads all pages under configured Pricing Documentation roots
- **Searches past Slack history** using semantic search (RAG with ChromaDB + Vertex AI embeddings)
- **Handles Jira requests** — search issues, get details, create tickets (default project: CLOGBI)
- **Knows all Pricing BigQuery tables** — schema catalog injected into every response
- **Logs all Q&As** to `logistics-customer-staging.price_gandalf.qa_logs` for usage tracking
- **Confluence correction flow** — authorised users can correct bot answers with `fix:` / `confirm` / `cancel`

---

## Architecture

```
Slack (Socket Mode WebSocket)
        │
        ▼
  Cloud Run (price-gandalf)
        │
        ├── Gemini 2.5 Flash (Vertex AI)
        │     └── System prompt: Confluence pages + BigQuery schema catalog
        │
        ├── ChromaDB (embedded in container)
        │     └── Slack channel history embeddings (pre-built, bundled at deploy time)
        │
        ├── Jira Cloud API
        └── BigQuery (Q&A logging)
```

---

## Setup

### 1. Prerequisites

- GCP project with billing enabled (`logistics-customer-staging`)
- Slack workspace admin access
- Confluence/Jira API access (Atlassian Cloud)
- GCP service account with roles:
  - `roles/aiplatform.user`
  - `roles/bigquery.dataEditor`
  - `roles/secretmanager.secretAccessor`

### 2. Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch**
2. Under **OAuth & Permissions → Bot Token Scopes**, add:
   ```
   app_mentions:read, channels:history, channels:read, chat:write,
   groups:history, groups:read, im:history, im:read, im:write, users:read
   ```
3. Under **Socket Mode** → enable and generate an App-Level Token (`connections:write`) → `SLACK_APP_TOKEN`
4. Install app to workspace → copy Bot User OAuth Token → `SLACK_BOT_TOKEN`
5. Invite bot to your channel: `/invite @Price Gandalf`

### 3. Environment variables

Copy `.env.example` to `.env` and fill in:

```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_USER_TOKEN=xoxe.xoxp-...        # for RAG pipeline only

GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GOOGLE_CLOUD_PROJECT=logistics-customer-staging
VERTEX_AI_LOCATION=us-central1
VERTEX_AI_MODEL=gemini-2.5-flash

JIRA_URL=https://deliveryhero.atlassian.net
CONFLUENCE_URL=https://deliveryhero.atlassian.net
JIRA_EMAIL=you@deliveryhero.com
JIRA_API_TOKEN=...
JIRA_DEFAULT_PROJECT=CLOGBI

PRICING_CHANNEL_ID=C...               # Slack channel ID to auto-reply in
FEEDBACK_USERS=U...,U...              # Slack user IDs allowed to submit corrections
GCS_RAG_BUCKET=                       # optional: GCS bucket for RAG index
```

### 4. Configure Confluence pages

Edit `slack_bot/confluence_context.py` — add root page IDs and all child pages are fetched automatically:

```python
_ROOT_PAGES = [
    ("Pricing Documentation", "36640152", "LOGCPL"),
    ("Dynamic Pricing Service", "67470918", "LOGCPL"),
    ("Pricing Domain - Customer Tribe", "36641669", "LOGCPL"),
]
```

### 5. Build the RAG index

```bash
python data/fetch_conversations.py                          # fetch last 90 days
python data/fetch_conversations.py --days 180               # or longer
python data/fetch_conversations.py --channels log-dps-analytics pricing-data  # multiple channels

python data/create_embeddings.py                            # build ChromaDB index
```

### 6. Test locally

```bash
python -m slack_bot.bot      # full Slack bot
python ask.py                # local CLI (no Slack needed)
```

### 7. Deploy to Cloud Run

```bash
bash deploy.sh
```

The script enables APIs, stores secrets in Secret Manager, builds a `linux/amd64` Docker image, and deploys to Cloud Run with the right flags for a persistent WebSocket connection.

---

## Confluence correction flow

Authorised users (set via `FEEDBACK_USERS`) can correct bot answers:

1. In the bot's reply thread, type: `fix: The correct information is X`
2. Bot proposes an edit to the relevant Confluence page
3. Reply `confirm` to apply or `cancel` to discard

---

## Refreshing the RAG index

Run periodically (e.g. monthly) as the channel accumulates new messages:

```bash
python data/fetch_conversations.py
python data/create_embeddings.py
bash deploy.sh
```

---

## Cost

| Service | Billed by |
|---|---|
| Vertex AI — Gemini 2.5 Flash | Input + output tokens per response |
| Vertex AI — text-embedding-005 | Tokens embedded (only when rebuilding RAG index) |
| Cloud Run | vCPU + memory per second (min 1 instance) |
| BigQuery | Bytes scanned for Q&A log queries |

Token usage is logged to Cloud Run logs on every response:
```
💰 Gemini usage — in: 4,231 tokens, out: 312 tokens, total: 4,543 tokens
```
