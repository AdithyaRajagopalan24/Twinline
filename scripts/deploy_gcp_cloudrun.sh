#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:?Usage: $0 PROJECT_ID CLOUDSQL_INSTANCE}"
CLOUDSQL_INSTANCE="${2:?Provide Cloud SQL Connection Name (PROJECT:REGION:INSTANCE)}"
REGION="${3:-asia-south1}"
DB_NAME="${4:-twinline_db}"
DB_USER="${5:-postgres}"

gcloud config set project "$PROJECT_ID" --quiet

# Deploy Backend: Fetch password directly from Secret Manager
gcloud run deploy twinline-backend \
  --source ./backend \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 1 \
  --add-cloudsql-instances "$CLOUDSQL_INSTANCE" \
  --set-env-vars "DB_SOCKET_DIR=/cloudsql/$CLOUDSQL_INSTANCE,DB_USER=$DB_USER,DB_NAME=$DB_NAME" \
  --set-secrets "DB_PASS=twinline-db-pass:latest"

BACKEND_URL=$(gcloud run services describe twinline-backend --region "$REGION" --format='value(status.url)')

# Deploy Frontend
gcloud run deploy twinline-dashboard \
  --source ./dashboard \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars "TWINLINE_API=$BACKEND_URL"



