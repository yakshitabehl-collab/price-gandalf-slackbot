#!/bin/bash
# Deploy Price Gandalf to Cloud Run.
# Run once to set up, then re-run whenever you update the bot.
#
# Prerequisites:
#   gcloud auth login
#   gcloud config set project logistics-customer-staging

set -euo pipefail

PROJECT_ID="logistics-customer-staging"
REGION="us-central1"
SERVICE_NAME="price-gandalf"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
RAG_BUCKET="${PROJECT_ID}-price-gandalf-rag"

# ── 1. Enable required APIs ──────────────────────────────────────────────────
echo "==> Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  containerregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com \
  --project="$PROJECT_ID"

# ── 2. Store secrets in Secret Manager ────────────────────────────────────────
echo "==> Setting up Secret Manager secrets..."

create_or_update_secret() {
  local name="$1"
  local value="$2"
  if gcloud secrets describe "$name" --project="$PROJECT_ID" &>/dev/null; then
    echo "    Updating secret: $name"
    echo -n "$value" | gcloud secrets versions add "$name" --data-file=- --project="$PROJECT_ID"
  else
    echo "    Creating secret: $name"
    echo -n "$value" | gcloud secrets create "$name" --data-file=- --project="$PROJECT_ID"
  fi
}

set -a; source .env; set +a

create_or_update_secret "PRICE_GANDALF_SLACK_BOT_TOKEN"  "$SLACK_BOT_TOKEN"
create_or_update_secret "PRICE_GANDALF_SLACK_APP_TOKEN"  "$SLACK_APP_TOKEN"
create_or_update_secret "PRICE_GANDALF_JIRA_API_TOKEN"   "$JIRA_API_TOKEN"
create_or_update_secret "PRICE_GANDALF_SA_JSON"          "$(cat logistics-customer-staging.json)"

# ── 3. Grant Cloud Run SA access to secrets ───────────────────────────────────
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
SA_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "==> Granting Secret Manager access to: $SA_EMAIL"
for SECRET in PRICE_GANDALF_SLACK_BOT_TOKEN PRICE_GANDALF_SLACK_APP_TOKEN PRICE_GANDALF_JIRA_API_TOKEN PRICE_GANDALF_SA_JSON; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$PROJECT_ID" \
    --quiet
done

# ── 4. Build and push image ───────────────────────────────────────────────────
echo "==> Configuring Docker to authenticate with GCR..."
gcloud auth configure-docker --quiet

DOCKER="/opt/homebrew/bin/docker"
export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"

echo "==> Building and pushing image for linux/amd64..."
"$DOCKER" buildx build \
  --platform linux/amd64 \
  --push \
  -t "${IMAGE}:latest" \
  .

# ── 5. Deploy to Cloud Run ────────────────────────────────────────────────────
echo "==> Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "${IMAGE}:latest" \
  --region "$REGION" \
  --platform managed \
  --min-instances 1 \
  --max-instances 1 \
  --no-allow-unauthenticated \
  --no-cpu-throttling \
  --memory 1Gi \
  --set-env-vars "^|^GOOGLE_CLOUD_PROJECT=${PROJECT_ID}|VERTEX_AI_LOCATION=us-central1|VERTEX_AI_MODEL=gemini-2.5-flash|JIRA_URL=https://deliveryhero.atlassian.net|JIRA_EMAIL=${JIRA_EMAIL}|JIRA_DEFAULT_PROJECT=CLOGBI|PRICING_CHANNEL_ID=${PRICING_CHANNEL_ID:-}|FEEDBACK_USERS=${FEEDBACK_USERS:-}|GCS_RAG_BUCKET=${RAG_BUCKET}" \
  --set-secrets "\
SLACK_BOT_TOKEN=PRICE_GANDALF_SLACK_BOT_TOKEN:latest,\
SLACK_APP_TOKEN=PRICE_GANDALF_SLACK_APP_TOKEN:latest,\
JIRA_API_TOKEN=PRICE_GANDALF_JIRA_API_TOKEN:latest,\
GOOGLE_APPLICATION_CREDENTIALS=PRICE_GANDALF_SA_JSON:latest"

# ── 6. GCS bucket for RAG index ──────────────────────────────────────────────
echo "==> Setting up GCS bucket for RAG index: gs://${RAG_BUCKET}/"
gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://${RAG_BUCKET}/" 2>/dev/null || echo "    Bucket already exists"

echo ""
echo "✅ Price Gandalf deployed!"
echo "   Logs: gcloud run logs tail $SERVICE_NAME --region $REGION"
