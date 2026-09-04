FROM ghcr.io/osgeo/gdal:ubuntu-small-3.12.2

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      postgresql-client \
      curl \
      ca-certificates \
      jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# The container runs as the invoking user, so the venv must be writable by
# any uid. UV_PROJECT_ENVIRONMENT points here from docker-compose.yml.
# The container runs as the invoking user, whose uid usually has no passwd
# entry, so HOME is unset and anything defaulting under ~ is unwritable.
# Give uv explicit, world-writable locations instead.
RUN mkdir -p /opt/uv-venv /opt/uv-cache && chmod 777 /opt/uv-venv /opt/uv-cache
ENV UV_LINK_MODE=copy \
    UV_CACHE_DIR=/opt/uv-cache

COPY docker/agent/entrypoint.sh /usr/local/bin/agent-entrypoint.sh
RUN chmod +x /usr/local/bin/agent-entrypoint.sh

WORKDIR /workspace
