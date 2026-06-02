import hashlib
import hmac
import json
import os
import urllib.request

import boto3

ecs = boto3.client("ecs")


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    mac = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={mac}", signature)


def get_registration_token(repo_url: str, github_token: str) -> str:
    # repo_url: https://github.com/owner/repo
    parts = repo_url.rstrip("/").split("/")
    owner, repo = parts[-2], parts[-1]

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runners/registration-token"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["token"]


def start_runner(repo_url: str, reg_token: str) -> str:
    response = ecs.run_task(
        cluster=os.environ["ECS_CLUSTER"],
        taskDefinition=os.environ["TASK_DEFINITION"],
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": os.environ["SUBNETS"].split(","),
                "securityGroups": os.environ["SECURITY_GROUPS"].split(","),
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": "runner",
                    "environment": [
                        {"name": "REPO_URL", "value": repo_url},
                        {"name": "REG_TOKEN", "value": reg_token},
                        {"name": "RUNNER_LABELS", "value": os.environ.get("RUNNER_LABELS", "self-hosted,ecs,linux")},
                    ],
                }
            ]
        },
    )
    task_arn = response["tasks"][0]["taskArn"]
    print(f"Started ECS task: {task_arn}")
    return task_arn


def handler(event, context):
    body_raw = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64
        body_raw = base64.b64decode(body_raw).decode()

    # Verify GitHub webhook signature
    webhook_secret = os.environ["WEBHOOK_SECRET"]
    signature = event.get("headers", {}).get("x-hub-signature-256", "")
    if not verify_signature(body_raw.encode(), signature, webhook_secret):
        return {"statusCode": 401, "body": "Invalid signature"}

    payload = json.loads(body_raw)

    # Only act on queued jobs
    if payload.get("action") != "queued":
        return {"statusCode": 200, "body": "Ignored"}

    # Only handle jobs targeting self-hosted runners
    job = payload.get("workflow_job", {})
    labels = job.get("labels", [])
    if "self-hosted" not in labels:
        return {"statusCode": 200, "body": "Not a self-hosted job"}

    repo_url = payload["repository"]["html_url"]
    github_token = os.environ["GITHUB_TOKEN"]

    reg_token = get_registration_token(repo_url, github_token)
    task_arn = start_runner(repo_url, reg_token)

    return {"statusCode": 200, "body": json.dumps({"task": task_arn})}
