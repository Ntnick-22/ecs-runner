FROM ubuntu:22.04

ARG RUNNER_VERSION=2.334.0

ENV DEBIAN_FRONTEND=noninteractive

# Install only what the runner actually needs — single layer, clean up in same step
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    jq \
    unzip \
    ca-certificates \
    libicu70 \
    libssl3 \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# AWS CLI — install and clean up installer immediately
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli \
    && rm -rf /tmp/awscliv2.zip /tmp/aws \
    && aws --version

# GitHub Actions runner
RUN useradd -m -s /bin/bash runner
WORKDIR /home/runner

RUN curl -fsSL \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
    | tar -xz \
    && rm -rf /home/runner/externals/node12 \
    && chown -R runner:runner /home/runner

COPY start.sh /home/runner/start.sh
RUN chmod +x /home/runner/start.sh

USER runner

ENTRYPOINT ["/home/runner/start.sh"]
