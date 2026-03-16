#!/usr/bin/env bash
# deploy.sh — Build and deploy the Fionaa Streamlit app to GCP Cloud Run
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
#
# Prerequisites:
#   - gcloud CLI authenticated: gcloud auth login
#   - Application default credentials: gcloud auth application-default login
#   - Project set: gcloud config set project fionaa-483715

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ID="fionaa-483715"
REGION="europe-west1"
SERVICE_NAME="fionaa-app"
SERVICE_ACCOUNT="developerserviceaccount@fionaa-483715.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/${SERVICE_NAME}"

# ── Ensure Artifact Registry repo exists ─────────────────────────────────────

echo "▶ Ensuring Artifact Registry repository..."
gcloud artifacts repositories describe cloud-run-source-deploy \
    --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null \
|| gcloud artifacts repositories create cloud-run-source-deploy \
    --repository-format=docker \
    --location="${REGION}" \
    --project="${PROJECT_ID}"

# ── Create Secret Manager secrets (idempotent) ────────────────────────────────
# Run this block once. Subsequent deploys skip creation if the secret exists.

create_secret() {
    local name="$1"
    local value="$2"
    if gcloud secrets describe "${name}" --project="${PROJECT_ID}" &>/dev/null; then
        echo "  secret ${name} already exists — skipping"
    else
        echo "  creating secret ${name}"
        echo -n "${value}" | gcloud secrets create "${name}" \
            --data-file=- \
            --replication-policy=automatic \
            --project="${PROJECT_ID}"
    fi
}

echo "▶ Setting up Secret Manager secrets..."

# Load .env — strip spaces around '=', quotes, and comment lines so bash can parse it
_load_env() {
    local file="${1:-.env}"
    while IFS= read -r line || [[ -n "$line" ]]; do
        # skip blank lines and comments
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue
        # strip inline comments
        line="${line%%#*}"
        # strip spaces around '='
        line="$(echo "$line" | sed 's/[[:space:]]*=[[:space:]]*/=/')"
        # strip surrounding quotes from value
        if [[ "$line" == *=* ]]; then
            local key="${line%%=*}"
            local val="${line#*=}"
            val="${val%\"}" ; val="${val#\"}"
            val="${val%\'}" ; val="${val#\'}"
            export "$key"="$val"
        fi
    done < "$file"
}
_load_env .env

create_secret "OPENAI_API_KEY"          "${OPENAI_API_KEY}"
create_secret "ANTHROPIC_API_KEY"       "${ANTHROPIC_API_KEY}"
create_secret "GOOGLE_MAPS_API_KEY"     "${GOOGLE_MAPS_API_KEY}"
create_secret "COMPANIES_HOUSE_API_KEY" "${COMPANIES_HOUSE_API_KEY}"
create_secret "TAVILY_API_KEY"          "${TAVILY_API_KEY}"
create_secret "COHERE_API_KEY"          "${COHERE_API_KEY}"
create_secret "LANGSMITH_API_KEY"       "${LANGSMITH_API_KEY}"
create_secret "VISION_AGENT_API_KEY"    "${VISION_AGENT_API_KEY}"

# Grant the service account access to read all secrets
echo "▶ Granting Secret Manager access to service account..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None \
    --quiet

# ── Build image via Cloud Build ───────────────────────────────────────────────

echo "▶ Building image with Cloud Build..."
gcloud builds submit . \
    --tag="${IMAGE}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}"

# ── Deploy to Cloud Run ───────────────────────────────────────────────────────

echo "▶ Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --service-account="${SERVICE_ACCOUNT}" \
    --allow-unauthenticated \
    --port=8080 \
    --memory=4Gi \
    --cpu=2 \
    --timeout=300 \
    --concurrency=10 \
    --min-instances=0 \
    --max-instances=3 \
    --set-env-vars="\
BUCKET_NAME=fionaa-customer-assets,\
GOOGLE_CLOUD_PROJECT=fionaa-483715,\
LANGSMITH_TRACING_V2=true,\
LANGSMITH_PROJECT=Fionaa,\
RUN_WITHOUT_OCR=true,\
RUN_WITHOUT_INTERNET_SEARCH=true,\
CH_MCP_SERVICE_URL=https://companies-house-mcp-660196542212.europe-west1.run.app/,\
LINKEDIN_MCP_SERVICE_URL=https://linkedin-mcp-server-660196542212.europe-west1.run.app/,\
LANGGRAPH_URL=${LANGGRAPH_URL}" \
    --set-secrets="\
OPENAI_API_KEY=OPENAI_API_KEY:latest,\
ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,\
GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY:latest,\
COMPANIES_HOUSE_API_KEY=COMPANIES_HOUSE_API_KEY:latest,\
TAVILY_API_KEY=TAVILY_API_KEY:latest,\
COHERE_API_KEY=COHERE_API_KEY:latest,\
LANGSMITH_API_KEY=LANGSMITH_API_KEY:latest,\
VISION_AGENT_API_KEY=VISION_AGENT_API_KEY:latest"

echo ""
echo "✓ Deployment complete."
gcloud run services describe "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --format="value(status.url)"
