# qbt-rules: multi-stage build. Template-owned skeleton; project-specific
# stages (extra binaries, assets) go between the builder and the runtime stage.

# ============================================================
# Stage 1: builder
# ============================================================
FROM python:3.13-slim AS builder

# git, for uv to fetch interpose (pinned to a git tag: template-python decision 0003),
# and the `build:` packages in contrib/system-packages.txt (project-owned): compilers
# and headers for dependencies that build from source
# hadolint ignore=DL3008,SC2046
RUN --mount=type=bind,source=contrib/system-packages.txt,target=/tmp/system-packages.txt \
    set -- git $(sed -n 's/^build://p' /tmp/system-packages.txt); \
    if [ $# -gt 0 ]; then \
        apt-get update \
        && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@" \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# Dependencies, then the package, into /opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

# From the lock file, compiled, without dev dependencies, with the base image's
# Python (never a downloaded one)
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

# Dependencies first, so a source change doesn't reinstall them
# with the optional extras the Copier answer `image_extras` names
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra redis

COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable --extra redis

# ============================================================
# Stage 2: runtime
# ============================================================
FROM python:3.13-slim

# Set by CI (docker-build.yml) from the release; OCI labels for `docker inspect`
ARG VERSION=0.0.0
ARG REVISION=unknown
ARG CREATED=unknown
LABEL org.opencontainers.image.title="qbt-rules" \
      org.opencontainers.image.description="A rules engine for qBittorrent automation, with a job queue, scheduler and web dashboard" \
      org.opencontainers.image.source="https://github.com/andronics/qbt-rules" \
      org.opencontainers.image.documentation="https://github.com/andronics/qbt-rules/wiki" \
      org.opencontainers.image.licenses="Unlicense" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}"

# The `runtime:` packages in contrib/system-packages.txt: libraries and tools the
# project needs at run time. None listed: nothing runs
# hadolint ignore=DL3008,SC2046
RUN --mount=type=bind,source=contrib/system-packages.txt,target=/tmp/system-packages.txt \
    set -- $(sed -n 's/^runtime://p' /tmp/system-packages.txt); \
    if [ $# -gt 0 ]; then \
        apt-get update \
        && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@" \
        && rm -rf /var/lib/apt/lists/*; \
    fi

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN useradd --system --create-home --shell /usr/sbin/nologin --uid 1000 qbt-rules

# Config is mounted at /etc/qbt-rules (missing is fine: defaults and
# QBT_RULES_* variables apply); state lives in /var/lib/qbt-rules
RUN mkdir -p /etc/qbt-rules /var/lib/qbt-rules \
    && chown qbt-rules:qbt-rules /var/lib/qbt-rules
COPY contrib/qbt-rules.example.yaml /usr/share/qbt-rules/config.example.yaml

# Relative paths resolve in the state directory, never in / (where an old
# volume such as /config could be read by mistake): template-python decision 0009
WORKDIR /var/lib/qbt-rules

# Bind every interface whatever the app's default: in a container, the
# published ports decide what is reachable, and loopback would be unreachable
ENV QBT_RULES_LISTEN_HOST=0.0.0.0

# Starts as root only to give the state directory to PUID:PGID (default
# 1000:1000), then drops to that user: see docker/entrypoint.sh. It shadows the
# real command on PATH so `docker exec <c> qbt-rules ...` goes through it too.
COPY docker/entrypoint.sh /opt/qbt-rules/bin/qbt-rules
RUN chmod 0755 /opt/qbt-rules/bin/qbt-rules
ENV PATH="/opt/qbt-rules/bin:$PATH"

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('QBT_RULES_LISTEN_PORT', '5000')}/healthz\", timeout=4)"]

EXPOSE 5000
VOLUME ["/var/lib/qbt-rules"]

ENTRYPOINT ["qbt-rules"]
CMD ["serve"]
