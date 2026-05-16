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
                self.albums_created > 0,
                self.albums_renamed > 0,
                self.albums_deleted > 0,
                self.assets_added > 0,
                self.assets_removed > 0,
                self.favorites.favorited > 0,
                self.favorites.unfavorited > 0,
                self.ratings.set > 0,
                self.ratings.cleared > 0,
                self.rejects.archived > 0,
                self.rejects.unarchived > 0,
                self.color_labels.tagged > 0,
                self.color_labels.untagged > 0,
                self.keywords.tagged > 0,
                self.keywords.untagged > 0,
                self.covers.set > 0,
                self.covers.cleared > 0,
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
