FROM python:3.12-slim

# Install system dependencies and build pimsync from source
RUN apt-get update && apt-get install -y \
    curl \
    git \
    make \
    build-essential \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/* \
    # Install Rust via rustup (Debian's rust is too old)
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable \
    && . "$HOME/.cargo/env" \
    # Clone and build pimsync
    && git clone https://git.sr.ht/~whynothugo/pimsync /tmp/pimsync \
    && cd /tmp/pimsync \
    && make build \
    && make install \
    && cd / \
    && rm -rf /tmp/pimsync \
    # Clean up Rust and build dependencies to reduce image size
    && rustup self uninstall -y \
    && apt-get remove -y git make \
    && apt-get autoremove -y \
    && apt-get clean

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install supercronic
ENV SUPERCRONIC_VERSION=v0.2.33 \
    SUPERCRONIC_SHA1SUM=71b0d58cc53f6bd72cf2f293e09e294b79c666d8 \
    SUPERCRONIC=supercronic-linux-amd64
RUN curl -fsSLO "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/${SUPERCRONIC}" \
    && echo "${SUPERCRONIC_SHA1SUM}  ${SUPERCRONIC}" | sha1sum -c - \
    && chmod +x "${SUPERCRONIC}" \
    && mv "${SUPERCRONIC}" /usr/local/bin/supercronic

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml README.md ./
COPY birthday_filter/ ./birthday_filter/

# Install Python dependencies
RUN uv pip install --system --no-cache -e .

# Create data directory
RUN mkdir -p /data

# Copy crontab
COPY crontab /app/crontab

# Run supercronic as the main process
# Use -no-reap to avoid "Failed to fork exec" error when running as PID 1
CMD ["supercronic", "-no-reap", "/app/crontab"]
