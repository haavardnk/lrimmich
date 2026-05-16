from dataclasses import asdict, dataclass, field
from typing import Any

from lrimmich.sync.albums import AlbumAction
from lrimmich.sync.color_labels import ColorLabelsResult
from lrimmich.sync.covers import CoversResult
from lrimmich.sync.favorites import FavoritesResult
from lrimmich.sync.keywords import KeywordsResult
from lrimmich.sync.ratings import RatingsResult
from lrimmich.sync.rejects import RejectsResult


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


def count_album_actions(actions: list[AlbumAction]) -> dict[str, int]:
    counts: dict[str, int] = {
        "created": 0,
        "renamed": 0,
        "deleted": 0,
        "assets_added": 0,
        "assets_removed": 0,
    }
    for a in actions:
        match a.kind:
            case "create":
                counts["created"] += 1
            case "rename":
                counts["renamed"] += 1
            case "delete":
                counts["deleted"] += 1
            case "add_assets":
                counts["assets_added"] += len(a.asset_ids)
            case "remove_assets":
                counts["assets_removed"] += len(a.asset_ids)
    return counts
