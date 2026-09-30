from dataclasses import dataclass, field
from functools import cached_property
from typing import Protocol, TypeVar

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
    async def plan(self, ctx: "SyncContext", summary: SyncSummary) -> PlanT: ...
    async def apply(self, plan: PlanT, ctx: "SyncContext") -> None: ...


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
    _tag_ids: dict[str, str] | None = field(default=None, repr=False)

    @cached_property
    def flagged(self) -> set[str]:
        return read_flagged_images(self.catalog.catalog)

    @cached_property
    def rejected(self) -> set[str]:
        return read_rejected_images(self.catalog.catalog)

    @cached_property
    def rated(self) -> dict[str, int]:
        return read_rated_images(self.catalog.catalog)

    async def get_tag_ids(self) -> dict[str, str]:
        if self._tag_ids is None:
            tags = await self.client.get_tags()
            self._tag_ids = {t["value"]: t["id"] for t in tags}
        return self._tag_ids

    async def ensure_tags(self, names: set[str]) -> dict[str, str]:
        tag_ids = await self.get_tag_ids()
        missing = sorted(names - tag_ids.keys())
        if missing:
            created = await self.client.upsert_tags(missing)
            tag_ids.update(zip(missing, (t["id"] for t in created), strict=True))
        return tag_ids
