FROM python:3.12-slim

# Install system dependencies including Rust for building pimsync
RUN apt-get update && apt-get install -y \
    git \
    curl \
    sudo \
    build-essential \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (needed for building pimsync)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install uv (as root, will be available system-wide)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Build and install pimsync from source
RUN git clone https://git.sr.ht/~whynothugo/pimsync /tmp/pimsync \
    && cd /tmp/pimsync \
    && make build \
    && make install \
    && rm -rf /tmp/pimsync

# Create a non-root user
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

USER $USERNAME
ENV PATH="/home/vscode/.local/bin:${PATH}"

# Switch back to root for any additional setup
USER root

WORKDIR /workspaces/birthday-filter
