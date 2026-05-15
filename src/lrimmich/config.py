import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

DEFAULT_CONFIG_PATH = Path("~/.config/lrimmich/config.toml").expanduser()


class BaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathMapping(BaseConfig):
    lr_path: str
    immich_path: str


class ExcludeConfig(BaseConfig):
    parent_ids: list[int] = []
    name_patterns: list[str] = []


class SyncConfig(BaseConfig):
    albums: bool = True
    favorites: bool = True
    ratings: bool = True
    tags: bool = True
    skip_empty: bool = True


class FavoritesConfig(BaseConfig):
    scope: str = "collections"

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        if v not in ("collections", "all"):
            raise ValueError("scope must be 'collections' or 'all'")
        return v


class SafetyConfig(BaseConfig):
    delete_threshold: int = 100
    remove_percent_limit: int = 50
    disable_deletes: bool = False


class Config(BaseConfig):
    catalog: Path
    immich_url: str
    api_key: str
    share_albums_with: list[str] = []
    path_map: list[PathMapping] = []
    exclude: ExcludeConfig = ExcludeConfig()
    sync: SyncConfig = SyncConfig()
    favorites: FavoritesConfig = FavoritesConfig()
    safety: SafetyConfig = SafetyConfig()

    @field_validator("catalog")
    @classmethod
    def expand_catalog(cls, v: Path) -> Path:
        return v.expanduser()


def load_config(path: Path | None = None) -> Config:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    return Config(**raw)
