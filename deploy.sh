#!/usr/bin/env bash
# Deploy the orchestrator to Cloud Run and wire Cloud Scheduler.
# Usage: PROJECT=my-proj ./deploy.sh
# Secrets must exist first (see README step 4): gemini-api-key, github-token,
# github-webhook-secret, gemini-webhook-secret, reconcile-token.
set -euo pipefail
PROJECT=${PROJECT:?set PROJECT}
REGION=${REGION:-asia-south1}
SERVICE=${SERVICE:-gemini-code-guru}
SA="code-guru@${PROJECT}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT"

gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create code-guru --display-name "Gemini Code Guru"
for role in roles/datastore.user roles/secretmanager.secretAccessor roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$role" --quiet >/dev/null
done

# Public URL is required for the GitHub and Gemini webhooks; both are signature-verified,
# /reconcile requires a bearer token, and the dashboard shows no secrets.
gcloud run deploy "$SERVICE" --source orchestrator --region "$REGION" \
  --service-account "$SA" --allow-unauthenticated \
  --min-instances 0 --max-instances 2 --concurrency 20 --timeout 300 \
  --set-env-vars "STORE=firestore,REPO=${REPO:-cmanikandan/Flask-AppBuilder},AGENT_ID=${AGENT_ID:-gemini-code-guru},MAX_CONCURRENT=3,RUN_TIMEOUT_MIN=60" \
  --set-secrets "GEMINI_API_KEY=gemini-api-key:latest,GH_TOKEN=github-token:latest,GITHUB_WEBHOOK_SECRET=github-webhook-secret:latest,GEMINI_WEBHOOK_SECRET=gemini-webhook-secret:latest,RECONCILE_TOKEN=reconcile-token:latest"

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')
TOKEN=$(gcloud secrets versions access latest --secret reconcile-token)

gcloud scheduler jobs describe code-guru-reconcile --location "$REGION" >/dev/null 2>&1 && \
  gcloud scheduler jobs delete code-guru-reconcile --location "$REGION" --quiet
gcloud scheduler jobs create http code-guru-reconcile --location "$REGION" \
  --schedule "*/10 * * * *" --time-zone "Asia/Kolkata" \
  --uri "$URL/reconcile" --http-method POST \
  --headers "Authorization=Bearer $TOKEN"

echo "Orchestrator: $URL"
echo "Next: python setup_gemini.py webhook --url $URL   and add the GitHub webhook -> $URL/github-webhook"
