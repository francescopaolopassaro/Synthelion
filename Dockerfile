# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Multi-stage build for the Synthelion dashboard/cluster-node image.
#
# What this image runs by default (see CMD): the read-only web dashboard,
# bound to 0.0.0.0 so it's reachable behind a load balancer / Kubernetes
# Service. It talks to whichever session/vector store `SYNTHELION_CONFIG`
# points at (local file, Redis, Postgres, ChromaDB, Qdrant) — see
# synthelion/config.py and docs/deploy/ for the cluster wiring.
#
# The synthelion CLI and `synthelion-mcp` (stdio MCP server) are both also
# available in this image — override CMD/entrypoint to run either instead,
# e.g. for a sidecar or a one-off `synthelion bench` job.
#
# Build:
#   docker build -t synthelion:latest .
# Run (single node, local file storage):
#   docker run -p 8787:8787 -v synthelion-data:/home/synthelion/.synthelion synthelion:latest
# Run (pointed at a shared config for cluster mode):
#   docker run -p 8787:8787 -v ./synthelion.config.json:/config/synthelion.config.json:ro \
#       -e SYNTHELION_CONFIG=/config/synthelion.config.json synthelion:latest

FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml LICENSE README.md ./
COPY synthelion ./synthelion
RUN pip install --no-cache-dir --prefix=/install ".[cluster]"

FROM python:3.12-slim
LABEL org.opencontainers.image.title="Synthelion" \
      org.opencontainers.image.description="Universal token compressor and multi-session dashboard for AI agents" \
      org.opencontainers.image.source="https://github.com/francescopaolopassaro/synthelion"

# Non-root: the dashboard/session stores never need elevated privileges.
RUN useradd --create-home --uid 1000 synthelion
COPY --from=builder /install /usr/local

ENV SYNTHELION_CONFIG="" \
    PYTHONUNBUFFERED=1

# Pre-create the local-store dir (incl. the chromadb subdir) owned by the
# non-root user *before* declaring the volume — otherwise Docker seeds a
# named volume's first-use content from the image path as root:root and
# every write (chromadb's PersistentClient, the fallback JSONL ledger) fails
# with "Permission denied" the moment a volume gets mounted there.
RUN mkdir -p /home/synthelion/.synthelion/sessions && \
    chown -R synthelion:synthelion /home/synthelion/.synthelion

USER synthelion
WORKDIR /home/synthelion
# Default local-file session/vector store lives under ~/.synthelion — mount a
# volume here to persist it. Irrelevant when SYNTHELION_CONFIG points at a
# Redis/Postgres/Qdrant backend instead, but harmless either way.
VOLUME ["/home/synthelion/.synthelion"]
EXPOSE 8787 8788

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8787/api/summary', timeout=3)" || exit 1

CMD ["synthelion", "serve-dashboard", "--host", "0.0.0.0", "--port", "8787"]
