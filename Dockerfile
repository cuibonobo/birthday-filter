FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    pipx \
    && rm -rf /var/lib/apt/lists/*

# Install pimsync via pipx
RUN pipx install pimsync && pipx ensurepath
ENV PATH="/root/.local/bin:${PATH}"

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
COPY pyproject.toml poetry.lock* ./
COPY birthday_filter/ ./birthday_filter/

# Install Python dependencies
RUN pip install --no-cache-dir python-dotenv

# Create data directory
RUN mkdir -p /data

# Copy crontab
COPY crontab /app/crontab

# Run supercronic as the main process
CMD ["supercronic", "/app/crontab"]
