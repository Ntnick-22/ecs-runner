#!/bin/bash
set -e

# Required env vars (injected by Lambda when starting the ECS task):
# REPO_URL      - e.g. https://github.com/your-org/your-repo
# REG_TOKEN     - GitHub registration token (short-lived, from GitHub API)
# RUNNER_LABELS - comma-separated labels e.g. self-hosted,ecs,linux

echo "Configuring runner for ${REPO_URL}"

./config.sh \
  --url "${REPO_URL}" \
  --token "${REG_TOKEN}" \
  --labels "${RUNNER_LABELS:-self-hosted,ecs,linux}" \
  --name "ecs-runner-$(hostname)" \
  --ephemeral \
  --unattended \
  --disableupdate

echo "Starting runner..."
./run.sh
