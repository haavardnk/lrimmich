import os
import tomllib
from hashlib import sha256
from pathlib import Path
from typing import Literal

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, field_validator

AlbumCollision = Literal["merge", "prefix"]
AlbumMode = Literal["managed", "hybrid"]
AlbumFilter = Literal["all", "flagged", "unflagged", "rejected"]
AssetOrder = Literal["asc", "desc"]
SyncScope = Literal["collections", "all"]

DEFAULT_CONFIG_PATH = user_config_path("lrimmich") / "config.toml"


class BaseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CatalogConfig(BaseConfig):
    catalog: Path
    strip: str | None = None
    exclude_collections: list[int] = []
    exclude_patterns: list[str] = []

    @field_validator("catalog")
    @classmethod
    def expand_catalog(cls, v: Path) -> Path:
        return v.expanduser()

    @property
    def key(self) -> str:
        return sha256(str(self.catalog).encode()).hexdigest()[:12]


class ImmichConfig(BaseConfig):
    url: str
    api_key: str = ""
    library_paths: list[str]


class SyncConfig(BaseConfig):
    albums: bool = True
    favorites: bool = True
    ratings: bool = True
    tags: bool = True
    captions: bool = True
    rejects: bool = False
    stacks: bool = False
    scope: SyncScope = "collections"
    album_mode: AlbumMode = "managed"
    album_collision: AlbumCollision = "merge"
    album_filter: AlbumFilter = "all"
    album_min_rating: int = Field(default=0, ge=0, le=5)
    album_name_format: str = "{path}"
    skip_empty: bool = True
    share_albums_with: list[str] = []
    keyword_prefix: str | None = "lr:keyword:"
    color_prefix: str | None = "lr:color:"


class AlbumRule(BaseConfig):
    match: str | None = None
    id: int | None = None
    filter: AlbumFilter | None = None
    min_rating: int | None = Field(default=None, ge=0, le=5)
    description: str | None = None
    order: AssetOrder | None = None
    share_with: list[str] | None = None


class SafetyConfig(BaseConfig):
    delete_threshold: int = 100
    remove_percent_limit: int = 50
    disable_deletes: bool = False


class CacheConfig(BaseConfig):
    ttl_days: int = Field(default=90, ge=1)
    spot_check_pct: int = Field(default=5, ge=0, le=100)


class NotificationConfig(BaseConfig):
    url: str | None = None


class Config(BaseConfig):
    catalogs: list[CatalogConfig]
    immich: ImmichConfig
    sync: SyncConfig = SyncConfig()
    cache: CacheConfig = CacheConfig()
    album_rules: list[AlbumRule] = []
    safety: SafetyConfig = SafetyConfig()
    notification: NotificationConfig = NotificationConfig()


def load_config(path: Path | None = None) -> Config:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        msg = (
            f"Config not found: {config_path}\n"
            "Run 'lrimmich config init' to create one."
        )
        raise SystemExit(msg)
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    env_key = os.environ.get("LRIMMICH_API_KEY")
    if env_key:
        raw.setdefault("immich", {})["api_key"] = env_key
    cfg = Config(**raw)
    if not cfg.immich.api_key:
        msg = "immich.api_key required (set in config or LRIMMICH_API_KEY env var)"
        raise SystemExit(msg)
    return cfg
