# Rosie's always-on server: Telegram, reminders, brief/review and rosie-vault git sync.
# No microphone, no orb. See docs/SERVER.md.
#
#   docker compose up -d          (with docker-compose.yml and a .env next to it)
FROM python:3.12-slim

# git: rosie-vault is synced with its remote. tzdata comes from the Python package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config
# Editable install: Rosie finds config/SOUL.md and config/permissions.yaml next to her code.
RUN pip install --no-cache-dir -e . \
    && useradd --create-home --uid 1000 rosie \
    && mkdir -p /data && chown rosie:rosie /data

USER rosie
ENV ROSIE_DATA_DIR=/data \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]

HEALTHCHECK --interval=5m --timeout=30s CMD ["rosie", "--version"]
CMD ["rosie", "server"]
