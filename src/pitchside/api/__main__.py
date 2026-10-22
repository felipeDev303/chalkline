"""`uv run python -m pitchside.api` -> http://127.0.0.1:8000 (PORT and HOST override)."""

import os

import uvicorn

from pitchside.api.app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))
