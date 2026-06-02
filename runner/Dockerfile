FROM ubuntu:22.04

ARG RUNNER_VERSION=2.317.0

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    curl \
    git \
    jq \
    unzip \
    tar \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws

# GitHub Actions runner
RUN useradd -m runner
WORKDIR /home/runner

RUN curl -fsSL \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
    | tar -xz \
    && chown -R runner:runner /home/runner

COPY start.sh /home/runner/start.sh
RUN chmod +x /home/runner/start.sh

USER runner

ENTRYPOINT ["/home/runner/start.sh"]
