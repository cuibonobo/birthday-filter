FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    pipx \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Install uv (as root, will be available system-wide)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create a non-root user
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# Install pimsync for the vscode user
USER $USERNAME
RUN pipx install pimsync && pipx ensurepath
ENV PATH="/home/vscode/.local/bin:${PATH}"

# Switch back to root for any additional setup
USER root

WORKDIR /workspaces/birthday-filter
