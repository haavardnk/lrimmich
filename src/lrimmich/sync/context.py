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
from lrimmich.utils.config import Config

PlanT = TypeVar("PlanT")


class SyncStep(Protocol[PlanT]):
    name: str
    status_msg: str

    def enabled(self, cfg: Config) -> bool: ...
    def plan(self, ctx: "SyncContext", summary: SyncSummary) -> PlanT: ...
    def apply(self, plan: PlanT, ctx: "SyncContext") -> None: ...


@dataclass
class SyncContext:
    cfg: Config
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
    _existing_tags: list[dict[str, Any]] | None = field(default=None, repr=False)

    def get_flagged(self) -> set[str]:
        if self._flagged is None:
            self._flagged = read_flagged_images(self.cfg.lightroom.catalog)
        return self._flagged

    def get_rejected(self) -> set[str]:
        if self._rejected is None:
            self._rejected = read_rejected_images(self.cfg.lightroom.catalog)
        return self._rejected

    def get_rated(self) -> dict[str, int]:
        if self._rated is None:
            self._rated = read_rated_images(self.cfg.lightroom.catalog)
        return self._rated

    def get_existing_tags(self) -> list[dict[str, Any]]:
        if self._existing_tags is None:
            self._existing_tags = self.client.get_tags()
        return self._existing_tags
