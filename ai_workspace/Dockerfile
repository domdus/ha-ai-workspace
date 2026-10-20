FROM python:3.12-slim-bookworm

ARG VERSION=dev

LABEL \
  org.opencontainers.image.source="https://github.com/domdus/ha-ai-workspace" \
  org.opencontainers.image.description="Cursor SDK sidecar for Home Assistant AI Workspace" \
  io.hass.name="Cursor SDK" \
  io.hass.description="Cursor SDK sidecar for Home Assistant AI Workspace" \
  io.hass.version="${VERSION}" \
  io.hass.type="addon" \
  io.hass.arch="amd64|aarch64"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8090

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=cursor-sdk -r requirements.txt
COPY app ./app
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8090
CMD ["/run.sh"]
