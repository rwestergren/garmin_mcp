FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH \
    PORT=8080 \
    GARMIN_MCP_TRANSPORT=streamable-http \
    GARMIN_MCP_HOST=0.0.0.0 \
    GARMINTOKENS=/data/garmin \
    GARMINTOKENS_BASE64=/data/garmin_tokens_base64 \
    GARMIN_DISABLED_TOOLS=download_activity_file,set_fit_download_dir,download_course_gpx,upload_course

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --compile-bytecode \
    && mkdir -p /data/garmin \
    && chmod 700 /data /data/garmin

COPY scripts/container-entrypoint.sh /usr/local/bin/container-entrypoint
ENTRYPOINT ["/bin/sh", "/usr/local/bin/container-entrypoint"]
CMD ["garmin-mcp"]
