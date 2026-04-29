FROM python:3.14-alpine3.23 AS builder

RUN pip install --root-user-action=ignore --no-cache-dir --upgrade pip \
    && pip install --root-user-action=ignore --no-cache-dir uv

ENV UV_LINK_MODE=copy

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.14-alpine3.23
LABEL org.opencontainers.image.title="NetBox MCP Server Extended" \
      org.opencontainers.image.description="A write-enabled MCP server for NetBox (extended fork)" \
      org.opencontainers.image.url="https://github.com/thomaschristory/netbox-mcp-server-extended" \
      org.opencontainers.image.source="https://github.com/thomaschristory/netbox-mcp-server-extended" \
      org.opencontainers.image.vendor="thomaschristory" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONUNBUFFERED=1

RUN apk update && apk upgrade --no-cache \
    && apk add --no-cache ca-certificates \
    && addgroup -g 1000 appuser \
    && adduser -D -u 1000 -G appuser appuser

COPY --from=builder --chown=appuser:appuser /app /app

WORKDIR /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["netbox-mcp-server"]
