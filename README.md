# ECS Ephemeral GitHub Actions Runner

Run self-hosted GitHub Actions runners as ephemeral AWS Fargate containers. Each job spins up a fresh container, runs, and shuts down — no persistent runner to maintain.

---

## How It Works

```
Workflow triggers
       │
       ▼
start-runner  (ubuntu-latest)
  ├─ Authenticates to AWS via OIDC
  ├─ Calls GitHub API → gets runner registration token
  └─ Calls aws ecs run-task → launches Fargate container
            │
            ▼
     ECS container boots
       start.sh runs:
         ├─ Calls GitHub API → gets registration token
         ├─ Registers runner (--ephemeral, labels: self-hosted,ecs,linux)
         └─ Starts runner agent → goes ONLINE
            │
            ▼
do-work  (self-hosted runner on ECS)
  └─ Your CI steps run inside the Fargate container
     Runner deregisters itself after job completes
            │
            ▼
stop-runner  (ubuntu-latest, always runs)
  └─ Finds and stops the ECS task (safety net)
```

### Two Workflows

| Workflow | Purpose | When to run |
|---|---|---|
| `build-runner.yml` | Builds the runner Docker image and pushes to ECR | Once at setup, then only when `runner/` files change |
| `test-runner.yaml` | 3-job ephemeral runner test | Any time you want to test |

### Key Dependency

The `start-runner` job uses the open source action **[PasseiDireto/gh-runner-task-action](https://github.com/marketplace/actions/starts-a-github-self-hosted-runner)** to bridge GitHub and AWS. It does two things in one step:

1. Calls the GitHub API to get a short-lived runner registration token (using your PAT)
2. Calls `aws ecs run-task` to launch the Fargate container and injects the token + repo details as environment variables

Without this action you would need to write those two API calls manually in your workflow. This project uses it as-is and passes in the task definition name, cluster, and network config via `task-params.json`.

---

## Prepare Your Values

Collect these before you start. Every placeholder in this guide maps to one of these values — fill them in once here so you can copy-paste as you go.

| Placeholder | What it is | Where to find it |
|---|---|---|
| `YOUR_ACCOUNT_ID` | 12-digit AWS account ID | AWS Console → top-right account menu |
| `YOUR_REGION` | AWS region to deploy into | Your choice, e.g. `eu-west-1` |
| `YOUR_GITHUB_USERNAME` | GitHub username (owner of your fork) | GitHub → your profile |
| `YOUR_SUBNET_IDS` | Comma-separated public subnet IDs | Collected in Step 2g |
| `YOUR_SECURITY_GROUP_ID` | Security group ID for the runner | Collected in Step 2g |
| `YOUR_RUNNER_PAT` | GitHub classic PAT with `repo` scope | Created in Step 3 |

Example with real values:
```bash
YOUR_ACCOUNT_ID=7722232323232
YOUR_REGION=eu-west-1
YOUR_GITHUB_USERNAME=Ntnick-22
YOUR_SUBNET_IDS=subnet-0c932512321e,subnet-018f31236666
YOUR_SECURITY_GROUP_ID=sg-0547ebb40d03e880f
YOUR_RUNNER_PAT=ghp_xxxxxxxxxxxxxxxxxxxx
```

---

## Prerequisites

- AWS account with permissions to create IAM roles, ECR, ECS, VPC resources
- GitHub account
- AWS CLI installed and configured locally

---

## Step 1 — Fork the Repo

Fork `Ntnick-22/ecs-runner` to your own GitHub account. All subsequent steps refer to your fork.

---

## Step 2 — AWS Setup

All resources should be in the same region. This guide uses `eu-west-1` — replace with your preferred region.

### 2a. Create the ECR Repository

```bash
aws ecr create-repository \
  --repository-name ecs-github-runner \
  --region YOUR_REGION
```

Note your account ID and region — the workflows construct the full ECR URI from them automatically.

### 2b. Create an ECS Cluster

```bash
aws ecs create-cluster \
  --cluster-name my-ecs-demo \
  --region YOUR_REGION
```

### 2c. Create a CloudWatch Log Group

```bash
aws logs create-log-group \
  --log-group-name /ecs/ecs-github-runner \
  --region YOUR_REGION
```

### 2d. Set Up the GitHub OIDC Provider in AWS

This allows GitHub Actions to authenticate to AWS without storing long-lived credentials.

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

> Skip this step if the provider already exists in your account (check **IAM → Identity Providers**). The thumbprint above is current but GitHub rotates it occasionally — if the CLI command fails, create the provider manually in the console to get the latest thumbprint automatically.

### 2e. Create the IAM Roles

You need three roles: one for GitHub Actions (OIDC), one as the ECS task role, and one as the ECS execution role.

---

#### Role 1: `github-actions-ecs-role`

This is assumed by your GitHub Actions workflow steps via OIDC.

**Trust policy** — save as `trust-github.json` (replace `YOUR_ACCOUNT_ID` and `YOUR_GITHUB_USERNAME`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::YOUR_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:YOUR_GITHUB_USERNAME/ecs-runner:*"
        }
      }
    }
  ]
}
```

**Permissions policy** — save as `policy-github-actions.json` (replace `YOUR_ACCOUNT_ID` and `YOUR_REGION`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "ECRPush",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "arn:aws:ecr:YOUR_REGION:YOUR_ACCOUNT_ID:repository/ecs-github-runner"
    },
    {
      "Sid": "ECSRunStop",
      "Effect": "Allow",
      "Action": [
        "ecs:RunTask",
        "ecs:StopTask",
        "ecs:ListTasks",
        "ecs:DescribeTasks"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::YOUR_ACCOUNT_ID:role/ecs-runner-task-role",
        "arn:aws:iam::YOUR_ACCOUNT_ID:role/ecsTaskExecutionRole"
      ]
    }
  ]
}
```

```bash
aws iam create-role \
  --role-name github-actions-ecs-role \
  --assume-role-policy-document file://trust-github.json

aws iam put-role-policy \
  --role-name github-actions-ecs-role \
  --policy-name github-actions-ecs-policy \
  --policy-document file://policy-github-actions.json
```

---

#### Role 2: `ecs-runner-task-role`

This is the IAM role the runner container itself assumes during the job. Add more permissions here when your jobs need to call other AWS services.

**Trust policy** — save as `trust-ecs.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

```bash
aws iam create-role \
  --role-name ecs-runner-task-role \
  --assume-role-policy-document file://trust-ecs.json
```

> No permissions are attached by default. Add policies here when your `do-work` job needs AWS access (e.g., S3, ECS, ECR).

---

#### Role 3: `ecsTaskExecutionRole`

Standard ECS execution role — used by the ECS agent to pull your image from ECR and write logs to CloudWatch.

```bash
aws iam create-role \
  --role-name ecsTaskExecutionRole \
  --assume-role-policy-document file://trust-ecs.json

aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

### 2f. Create the ECS Task Definition

Save as `task-def-register.json` (replace `YOUR_ACCOUNT_ID` and `YOUR_REGION`):

```json
{
  "family": "github-runner",
  "taskRoleArn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/ecs-runner-task-role",
  "executionRoleArn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/ecsTaskExecutionRole",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "runtimePlatform": {
    "cpuArchitecture": "X86_64",
    "operatingSystemFamily": "LINUX"
  },
  "containerDefinitions": [
    {
      "name": "runner",
      "image": "YOUR_ACCOUNT_ID.dkr.ecr.YOUR_REGION.amazonaws.com/ecs-github-runner:latest",
      "essential": true,
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/ecs-github-runner",
          "awslogs-region": "YOUR_REGION",
          "awslogs-stream-prefix": "runner"
        }
      }
    }
  ]
}
```

```bash
aws ecs register-task-definition \
  --cli-input-json file://task-def-register.json \
  --region YOUR_REGION
```

> **Prefer the console?** Go to **ECS → Task Definitions → Create new task definition**. Select Fargate, set CPU to 0.5 vCPU and memory to 1 GB, set the task role to `ecs-runner-task-role` and execution role to `ecsTaskExecutionRole`, add a container named `runner` pointing to your ECR image URI, and set the log driver to `awslogs` with log group `/ecs/ecs-github-runner`. Make sure the family name is exactly `github-runner` to match the workflow.

### 2g. Networking — Subnets and Security Group

The Fargate container needs outbound internet access to reach GitHub (`github.com`) and AWS APIs. Use a **public subnet** with `assignPublicIp: ENABLED`, or a private subnet behind a NAT gateway.

**Find your default VPC subnets:**
```bash
aws ec2 describe-subnets \
  --filters "Name=default-for-az,Values=true" \
  --query "Subnets[*].[SubnetId,AvailabilityZone]" \
  --output table \
  --region YOUR_REGION
```

**Create a security group** (outbound HTTPS only — no inbound needed):
```bash
# Get your default VPC ID
VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=is-default,Values=true" \
  --query "Vpcs[0].VpcId" \
  --output text \
  --region YOUR_REGION)

# Create security group
SG_ID=$(aws ec2 create-security-group \
  --group-name ecs-runner-sg \
  --description "ECS GitHub runner - outbound only" \
  --vpc-id $VPC_ID \
  --region YOUR_REGION \
  --query GroupId \
  --output text)

echo "Security group: $SG_ID"
```

The default security group allows all outbound — no extra rules needed. Note both subnet IDs and the security group ID.

---

## Step 3 — GitHub Secrets

In your forked repo go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `AWS_ACCOUNT_ID` | Your 12-digit AWS account ID |
| `AWS_ROLE_ARN` | `arn:aws:iam::YOUR_ACCOUNT_ID:role/github-actions-ecs-role` |
| `ECS_SUBNETS` | Comma-separated subnet IDs, e.g. `subnet-abc123,subnet-def456` |
| `ECS_SECURITY_GROUP` | Security group ID, e.g. `sg-0123456789` |
| `RUNNER_PAT` | A GitHub classic PAT (see below) |

### Creating the PAT

1. Go to GitHub → **Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token (classic)**
3. Give it a name, e.g. `ecs-runner-pat`
4. Select scope: **`repo`** (full control of private repositories)
5. Click **Generate token** and copy it immediately
6. Paste it as the `RUNNER_PAT` secret

> **Important:** Use a classic PAT, not a fine-grained PAT. The runner registration token API does not support fine-grained PATs.

---

## Step 4 — Build the Runner Image

Go to your repo → **Actions → Build & Push Runner Image** → **Run workflow**.

This builds the Docker image from `runner/Dockerfile` and pushes it to your ECR repository. It runs on `ubuntu-latest` (no self-hosted runner needed yet).

Wait for it to complete successfully before continuing.

---

## Step 5 — Run the Test

Go to **Actions → Test ECS Runner - 3 Jobs** → **Run workflow**.

You will see three jobs:

1. **Start self-hosted runner** — launches the ECS Fargate container
2. **Run job on self-hosted runner** — executes inside your container
3. **Stop self-hosted runner** — cleans up the ECS task

### Verifying It Worked

Once all three jobs pass:

1. Click on the completed workflow run
2. Scroll to the **Artifacts** section at the bottom
3. Download `ecs-runner-proof`
4. Open `index.html` in your browser

A sample of a successful output is included in this repo at [`ecs-runner-proof/index.html`](ecs-runner-proof/index.html). It looks like this:

```
ECS Ephemeral Runner - Job Proof
Hostname:  ip-10-0-79-232.eu-west-1.compute.internal
User:      runner
OS:        Linux ip-10-0-79-232.eu-west-1.compute.internal 6.1.170 x86_64 GNU/Linux
Ran at:    Thu Jun  4 09:00:44 UTC 2026
Repo:      Ntnick-22/ecs-runner
Run ID:    26941821729
```

The hostname (`ip-10-x-x-x`) confirms the job ran inside a real Fargate container in your VPC — not on a GitHub-hosted machine.

---

## Troubleshooting

### `start-runner` job fails — "ResourceNotFoundException: Task definition not found"
The task definition family name in `test-runner.yaml` (`TASK_DEFINITION: github-runner`) must match what you registered in Step 2f.

### `start-runner` job fails — "no runner picks up the job"
- Check CloudWatch logs at `/ecs/ecs-github-runner` — look for errors from `start.sh`
- Common cause: `RUNNER_PAT` secret is expired, wrong scope, or is a fine-grained PAT
- Common cause: ECR image doesn't exist yet — make sure Step 4 completed successfully

### `do-work` job hangs waiting for a runner
The ECS task likely failed to start. Check:
```bash
aws ecs list-tasks --cluster my-ecs-demo --region YOUR_REGION
```
If empty, the task stopped immediately. Check CloudWatch logs for the error.

### `build-runner` fails — ECR push denied
The `github-actions-ecs-role` trust policy condition must match your repo exactly:
```
repo:YOUR_GITHUB_USERNAME/ecs-runner:*
```
Verify the username and repo name match your fork.

### Any workflow step fails — "Not authorized to perform sts:AssumeRoleWithWebIdentity"
Your repo is not in the trust policy of `github-actions-ecs-role`. This is the most common issue when forking — the trust policy was created with the original repo name and won't allow your fork.

Go to **IAM → Roles → github-actions-ecs-role → Trust relationships** and check the `sub` condition:
```json
"token.actions.githubusercontent.com:sub": "repo:YOUR_GITHUB_USERNAME/ecs-runner:*"
```
If it still shows the original owner's username, edit it and replace with your own. Any workflow that uses `role-to-assume` will fail silently with a permissions error until this is fixed.

### Container can't reach GitHub
The Fargate task needs outbound HTTPS. Verify:
- Subnets are public (or have a NAT gateway)
- `assignPublicIp: ENABLED` in the task launch config (handled by the workflow)
- Security group allows outbound 443

---

## Repo Structure

```
ecs-runner/
├── runner/
│   ├── Dockerfile      # Runner image — Ubuntu + Actions runner binary + AWS CLI
│   └── start.sh        # Entrypoint — registers runner at boot, then starts it
└── .github/
    └── workflows/
        ├── build-runner.yml    # Builds and pushes runner image to ECR
        └── test-runner.yaml    # 3-job ephemeral runner test
```
