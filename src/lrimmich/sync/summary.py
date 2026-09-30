from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class FavoritesResult:
    favorited: int = 0
    unfavorited: int = 0


@dataclass
class RatingsResult:
    set: int = 0
    cleared: int = 0


@dataclass
class RejectsResult:
    archived: int = 0
    unarchived: int = 0


@dataclass
class CoversResult:
    set: int = 0


@dataclass
class TagSyncResult:
    tagged: int = 0
    untagged: int = 0


@dataclass
class CaptionsResult:
    set: int = 0
    cleared: int = 0


@dataclass
class StacksResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0


@dataclass
class SyncSummary:
    albums_created: int = 0
    albums_renamed: int = 0
    albums_deleted: int = 0
    assets_added: int = 0
    assets_removed: int = 0
    favorites: FavoritesResult = field(default_factory=FavoritesResult)
    ratings: RatingsResult = field(default_factory=RatingsResult)
    rejects: RejectsResult = field(default_factory=RejectsResult)
    color_labels: TagSyncResult = field(default_factory=TagSyncResult)
    keywords: TagSyncResult = field(default_factory=TagSyncResult)
    captions: CaptionsResult = field(default_factory=CaptionsResult)
    covers: CoversResult = field(default_factory=CoversResult)
    stacks: StacksResult = field(default_factory=StacksResult)
    skipped_unchanged: bool = False
    unresolved: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.changes())

    def changes(self) -> dict[str, int]:
        data = asdict(self)
        top = {k: v for k, v in data.items() if type(v) is int and k != "unresolved"}
        nested = {
            f"{k}.{sub}": count
            for k, v in data.items()
            if isinstance(v, dict)
            for sub, count in v.items()
        }
        return {k: v for k, v in (top | nested).items() if v}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def merge(self, other: "SyncSummary") -> None:
        for f in fields(self):
            val_self = getattr(self, f.name)
            val_other = getattr(other, f.name)
            if isinstance(val_self, bool):
                continue
            if isinstance(val_self, int):
                setattr(self, f.name, val_self + val_other)
            elif hasattr(val_self, "__dataclass_fields__"):
                for sub_f in fields(val_self):
                    setattr(
                        val_self,
                        sub_f.name,
                        getattr(val_self, sub_f.name) + getattr(val_other, sub_f.name),
                    )
        self.errors.extend(other.errors)
