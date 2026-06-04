#!/bin/bash
set -e

echo "Configuring runner for ${GITHUB_OWNER}/${GITHUB_REPOSITORY}"

REG_TOKEN=$(curl -s -X POST \
  -H "Authorization: token ${GITHUB_PERSONAL_TOKEN}" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPOSITORY}/actions/runners/registration-token" \
  | jq -r '.token')

if [ -z "$REG_TOKEN" ] || [ "$REG_TOKEN" = "null" ]; then
  echo "Failed to get registration token"
  exit 1
fi

./config.sh \
  --url "https://github.com/${GITHUB_OWNER}/${GITHUB_REPOSITORY}" \
  --token "${REG_TOKEN}" \
  --labels "${RUNNER_LABELS:-self-hosted,ecs,linux}" \
  --name "${RUNNER_NAME:-ecs-runner-$(hostname)}" \
  --ephemeral \
  --unattended \
  --disableupdate

echo "Starting runner..."
./run.sh
