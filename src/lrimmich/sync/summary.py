from dataclasses import asdict, dataclass, field
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
    covers: CoversResult = field(default_factory=CoversResult)
    errors: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return any(
            [
                self.albums_created,
                self.albums_renamed,
                self.albums_deleted,
                self.assets_added,
                self.assets_removed,
                self.favorites.favorited,
                self.favorites.unfavorited,
                self.ratings.set,
                self.ratings.cleared,
                self.rejects.archived,
                self.rejects.unarchived,
                self.color_labels.tagged,
                self.color_labels.untagged,
                self.keywords.tagged,
                self.keywords.untagged,
                self.covers.set,
                self.covers.cleared,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
