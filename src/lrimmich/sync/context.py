import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from lrimmich.clients.catalog import (
    LrCollection,
    read_flagged_images,
    read_rated_images,
    read_rejected_images,
)
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.config import CatalogConfig, Config

PlanT = TypeVar("PlanT")


class SyncStep(Protocol[PlanT]):
    name: str
    status_msg: str

    def enabled(self, cfg: Config) -> bool: ...
    def plan(
        self, ctx: "SyncContext", summary: SyncSummary
    ) -> Coroutine[Any, Any, PlanT]: ...
    def apply(self, plan: PlanT, ctx: "SyncContext") -> Coroutine[Any, Any, None]: ...


@dataclass
class SyncContext:
    cfg: Config
    catalog: CatalogConfig
    client: ImmichClient
    state: StateDB
    collections: list[LrCollection]
    resolved: dict[str, str]
    dry_run: bool
    force: bool
    no_delete: bool
    _flagged: set[str] | None = field(default=None, repr=False)
    _rejected: set[str] | None = field(default=None, repr=False)
    _rated: dict[str, int] | None = field(default=None, repr=False)
    _tag_ids: dict[str, str] | None = field(default=None, repr=False)
    _tags_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def get_flagged(self) -> set[str]:
        if self._flagged is None:
            self._flagged = read_flagged_images(self.catalog.catalog)
        return self._flagged

    def get_rejected(self) -> set[str]:
        if self._rejected is None:
            self._rejected = read_rejected_images(self.catalog.catalog)
        return self._rejected

    def get_rated(self) -> dict[str, int]:
        if self._rated is None:
            self._rated = read_rated_images(self.catalog.catalog)
        return self._rated

    async def get_tag_ids(self) -> dict[str, str]:
        async with self._tags_lock:
            if self._tag_ids is None:
                tags = await self.client.get_tags()
                self._tag_ids = {t["value"]: t["id"] for t in tags}
            return self._tag_ids

    async def ensure_tags(self, names: set[str]) -> dict[str, str]:
        tag_ids = await self.get_tag_ids()
        async with self._tags_lock:
            for name in sorted(names - tag_ids.keys()):
                tag_ids[name] = (await self.client.create_tag(name))["id"]
        return tag_ids
