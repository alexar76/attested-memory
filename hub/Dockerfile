FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 hub \
    && useradd --system --uid 10001 --gid hub --home-dir /app hub

COPY .upstreams/aimarket-hub/pyproject.toml ./pyproject.toml
COPY .upstreams/aimarket-hub/README.md .upstreams/aimarket-hub/LICENSE ./
COPY .upstreams/aimarket-hub/aimarket_hub ./aimarket_hub
COPY .upstreams/aimarket-hub/plugins-demo.html .upstreams/aimarket-hub/terminal-home.html ./
# The operator desk, which the landing links to from its nav AND from the knock rail
# ('Operator desk' beside the unapproved hubs). It was never copied, so /operator
# answered 404 on this hub while inviting every visitor to click it — and it is the
# page an operator approves a knocking hub from.
COPY .upstreams/aimarket-hub/operator.html ./
COPY .upstreams/aimarket-hub/cap-descriptions-i18n.json .upstreams/aimarket-hub/hub-ui-i18n.json ./
COPY .upstreams/aimarket-protocol/schemas ./aimarket-protocol/schemas
COPY hub/federation_bootstrap.py ./federation_bootstrap.py
COPY hub/rewrite_terminal_nav.py ./rewrite_terminal_nav.py
RUN python rewrite_terminal_nav.py && rm -f rewrite_terminal_nav.py

# PQ verification is installed deliberately. A hybrid document that reaches this
# Hub must be checked, never silently downgraded to its Ed25519 half.
RUN pip install --upgrade pip setuptools \
    && pip install -e ".[escrow,pqc,postgres]" "psycopg[binary,pool]>=3.2" uvicorn

RUN mkdir -p /data && chown -R hub:hub /app /data
USER hub:hub
EXPOSE 9083
HEALTHCHECK --interval=15s --timeout=3s --start-period=8s --retries=5 \
  CMD ["curl", "-fsS", "http://127.0.0.1:9083/ai-market/v2/health"]
ENTRYPOINT ["python", "-m", "aimarket_hub", "serve"]
