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
    cleared: int = 0


@dataclass
class TagSyncResult:
    tagged: int = 0
    untagged: int = 0


ColorLabelsResult = TagSyncResult
KeywordsResult = TagSyncResult


@dataclass
class CaptionsResult:
    set: int = 0
    cleared: int = 0


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
    color_labels: ColorLabelsResult = field(default_factory=ColorLabelsResult)
    keywords: KeywordsResult = field(default_factory=KeywordsResult)
    captions: CaptionsResult = field(default_factory=CaptionsResult)
    covers: CoversResult = field(default_factory=CoversResult)
    errors: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, int) and val:
                return True
            if hasattr(val, "__dataclass_fields__"):
                for sub_f in fields(val):
                    if getattr(val, sub_f.name):
                        return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
