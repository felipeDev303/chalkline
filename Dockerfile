# Pitchside: API + UI in one image. Keyless at runtime: Azure access comes from the
# container app's managed identity (AZURE_CLIENT_ID), never from files or keys.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 UV_PYTHON_DOWNLOADS=never

# Dependencies first, so code changes reuse this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY src ./src
RUN uv sync --frozen --no-editable

RUN useradd --create-home --uid 10001 pitchside
USER pitchside

ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "pitchside.api"]
