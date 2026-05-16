import os
import tomllib
from pathlib import Path
from typing import Literal

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, field_validator

DEFAULT_CONFIG_PATH = user_config_path("lrimmich") / "config.toml"


class BaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExcludeConfig(BaseConfig):
    collection_ids: list[int] = []
    name_patterns: list[str] = []


class SyncConfig(BaseConfig):
    albums: bool = True
    favorites: bool = True
    ratings: bool = True
    tags: bool = True
    rejects: bool = False
    skip_empty: bool = True
    scope: Literal["collections", "all"] = "collections"
    album_name_format: str = "{path}"
    notify_url: str = ""


class LightroomConfig(BaseConfig):
    catalog: Path
    strip: str = ""

    @field_validator("catalog")
    @classmethod
    def expand_catalog(cls, v: Path) -> Path:
        return v.expanduser()


class ImmichConfig(BaseConfig):
    url: str
    api_key: str = ""
    library_path: str
    share_albums_with: list[str] = []


class SafetyConfig(BaseConfig):
    delete_threshold: int = 100
    remove_percent_limit: int = 50
    disable_deletes: bool = False


class Config(BaseConfig):
    lightroom: LightroomConfig
    immich: ImmichConfig
    exclude: ExcludeConfig = ExcludeConfig()
    sync: SyncConfig = SyncConfig()
    safety: SafetyConfig = SafetyConfig()


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
