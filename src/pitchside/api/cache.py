"""Insight cache: memory in front of a durable store (a local folder, or Azure Blob).

Keys are a hash of the match and the full TurnRequest, so the UI and the precompute
script (scripts/precompute_insights.py) find the same entries. Blob access is keyless:
the app's managed identity (or `az login` locally) needs Storage Blob Data
Contributor on the container; the storage account has shared keys disabled.

    PITCHSIDE_CACHE_BLOB_URL  https://<account>.blob.core.windows.net/<container>
    PITCHSIDE_CACHE_DIR       a local folder (dev); ignored when the blob URL is set
"""

from __future__ import annotations

import hashlib
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Protocol

from pitchside.agents.contracts import Insight, TurnRequest


class Store(Protocol):
    async def get(self, name: str) -> str | None: ...
    async def put(self, name: str, text: str) -> None: ...


class DirStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def get(self, name: str) -> str | None:
        path = self.directory / name
        return path.read_text("utf-8") if path.exists() else None

    async def put(self, name: str, text: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / name).write_text(text, "utf-8")


class BlobStore:
    def __init__(self, container: Any) -> None:  # azure.storage.blob.aio.ContainerClient
        self.container = container

    async def get(self, name: str) -> str | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            blob = await self.container.download_blob(name, encoding="utf-8")
            return await blob.readall()
        except ResourceNotFoundError:
            return None

    async def put(self, name: str, text: str) -> None:
        await self.container.upload_blob(name, text.encode("utf-8"), overwrite=True)


async def open_store(stack: AsyncExitStack, cache_dir: Path | None = None) -> Store | None:
    """The configured durable store, closed with `stack`; None keeps memory only."""
    url = os.environ.get("PITCHSIDE_CACHE_BLOB_URL")
    if url:
        from azure.identity.aio import DefaultAzureCredential
        from azure.storage.blob.aio import ContainerClient

        credential = await stack.enter_async_context(DefaultAzureCredential())
        container = await stack.enter_async_context(
            ContainerClient.from_container_url(url, credential=credential))
        return BlobStore(container)
    directory = cache_dir or (Path(os.environ["PITCHSIDE_CACHE_DIR"])
                              if os.environ.get("PITCHSIDE_CACHE_DIR") else None)
    return DirStore(directory) if directory is not None else None


class InsightCache:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store
        self.memory: dict[str, Insight] = {}

    @staticmethod
    def key(match_id: str, request: TurnRequest) -> str:
        raw = f"{match_id}|{request.model_dump_json()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def get(self, key: str) -> Insight | None:
        if key not in self.memory and self.store is not None:
            text = await self.store.get(f"{key}.json")
            if text is not None:
                self.memory[key] = Insight.model_validate_json(text)
        return self.memory.get(key)

    async def put(self, key: str, insight: Insight) -> None:
        self.memory[key] = insight
        if self.store is not None:
            await self.store.put(f"{key}.json", insight.model_dump_json())


def cacheable(insight: Insight) -> bool:
    """A turn without a narrator (outage, no model) is retried, never remembered."""
    return not (insight.failure or "").startswith("narrator unavailable")
