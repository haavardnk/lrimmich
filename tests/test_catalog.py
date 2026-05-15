from pathlib import Path

import pytest

from lrimmich.catalog import (
    read_collections,
    read_color_labels,
    read_flagged_images,
    read_keywords,
    read_rated_images,
)
from lrimmich.config import ExcludeConfig
from tests.fixtures.catalog_factory import CatalogBuilder


@pytest.fixture()
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "test.lrcat"


def test_basic_collection(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_collection(1, "Vacation")
        .add_image(10, "IMG_001.jpg", "2024/jan/")
        .add_collection_image(1, 10)
        .build()
    )
    cols = read_collections(catalog_path)
    assert len(cols) == 1
    assert cols[0].id == 1
    assert cols[0].name == "Vacation"
    assert cols[0].full_name == "Vacation"
    assert cols[0].relative_paths == ["2024/jan/IMG_001.jpg"]


def test_nested_collection_sets(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_set(1, "Personal")
        .add_set(2, "2024", parent=1)
        .add_collection(3, "Summer", parent=2)
        .add_image(10, "beach.jpg", "raw/")
        .add_collection_image(3, 10)
        .build()
    )
    cols = read_collections(catalog_path)
    assert len(cols) == 1
    assert cols[0].full_name == "Personal/2024/Summer"


def test_duplicate_names_different_parents(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_set(1, "Work")
        .add_set(2, "Personal")
        .add_collection(3, "Favorites", parent=1)
        .add_collection(4, "Favorites", parent=2)
        .add_image(10, "a.jpg", "raw/")
        .add_image(11, "b.jpg", "raw/")
        .add_collection_image(3, 10)
        .add_collection_image(4, 11)
        .build()
    )
    cols = read_collections(catalog_path)
    names = sorted(c.full_name for c in cols)
    assert names == ["Personal/Favorites", "Work/Favorites"]


def test_empty_collection(catalog_path: Path) -> None:
    CatalogBuilder(catalog_path).add_collection(1, "Empty").build()
    cols = read_collections(catalog_path)
    assert len(cols) == 1
    assert cols[0].relative_paths == []


def test_skip_parent_filter(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_set(67, "From Lightroom")
        .add_collection(1, "Cloud Album", parent=67)
        .add_collection(2, "Local Album")
        .add_image(10, "a.jpg", "raw/")
        .add_collection_image(1, 10)
        .add_collection_image(2, 10)
        .build()
    )
    exclude = ExcludeConfig(parent_ids=[67])
    cols = read_collections(catalog_path, exclude=exclude)
    assert len(cols) == 1
    assert cols[0].name == "Local Album"


def test_name_pattern_filter(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_set(1, "_tmp")
        .add_collection(2, "scratch", parent=1)
        .add_collection(3, "Keepers")
        .build()
    )
    exclude = ExcludeConfig(name_patterns=["_tmp/*"])
    cols = read_collections(catalog_path, exclude=exclude)
    assert len(cols) == 1
    assert cols[0].name == "Keepers"


def test_system_collection_excluded(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_system_collection(1, "Quick Collection")
        .add_collection(2, "Real Album")
        .build()
    )
    cols = read_collections(catalog_path)
    assert len(cols) == 1
    assert cols[0].name == "Real Album"


def test_flagged_images(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_image(1, "picked.jpg", "2024/", pick=1)
        .add_image(2, "normal.jpg", "2024/", pick=0)
        .add_image(3, "rejected.jpg", "2024/", pick=-1)
        .add_image(4, "also_picked.jpg", "other/", pick=1)
        .build()
    )
    flagged = read_flagged_images(catalog_path)
    assert flagged == {"2024/picked.jpg", "other/also_picked.jpg"}


def test_no_flagged_images(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_image(1, "a.jpg", "raw/", pick=0)
        .add_image(2, "b.jpg", "raw/", pick=-1)
        .build()
    )
    flagged = read_flagged_images(catalog_path)
    assert flagged == set()


def test_multiple_images_in_collection(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_collection(1, "Trip")
        .add_image(10, "a.jpg", "2024/")
        .add_image(11, "b.jpg", "2024/")
        .add_image(12, "c.jpg", "2025/")
        .add_collection_image(1, 10)
        .add_collection_image(1, 11)
        .add_collection_image(1, 12)
        .build()
    )
    cols = read_collections(catalog_path)
    assert len(cols) == 1
    assert sorted(cols[0].relative_paths) == [
        "2024/a.jpg",
        "2024/b.jpg",
        "2025/c.jpg",
    ]


def test_rated_images(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_image(1, "five.jpg", "raw/", rating=5)
        .add_image(2, "three.jpg", "raw/", rating=3)
        .add_image(3, "unrated.jpg", "raw/", rating=0)
        .build()
    )
    rated = read_rated_images(catalog_path)
    assert rated == {"raw/five.jpg": 5, "raw/three.jpg": 3}


def test_no_rated_images(catalog_path: Path) -> None:
    CatalogBuilder(catalog_path).add_image(1, "a.jpg", "raw/").build()
    assert read_rated_images(catalog_path) == {}


def test_color_labels(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_image(1, "red.jpg", "raw/", color_labels="Red")
        .add_image(2, "blue.jpg", "raw/", color_labels="Blue")
        .add_image(3, "none.jpg", "raw/")
        .build()
    )
    labels = read_color_labels(catalog_path)
    assert labels == {"raw/red.jpg": "Red", "raw/blue.jpg": "Blue"}


def test_no_color_labels(catalog_path: Path) -> None:
    CatalogBuilder(catalog_path).add_image(1, "a.jpg", "raw/").build()
    assert read_color_labels(catalog_path) == {}


def test_keywords_flat(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_keyword(1, "landscape")
        .add_keyword(2, "portrait")
        .add_image(10, "a.jpg", "raw/")
        .add_keyword_image(1, 10)
        .add_keyword_image(2, 10)
        .build()
    )
    kw = read_keywords(catalog_path)
    assert sorted(kw["raw/a.jpg"]) == ["landscape", "portrait"]


def test_keywords_hierarchical(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_keyword(1, "Places")
        .add_keyword(2, "Europe", parent=1)
        .add_keyword(3, "Norway", parent=2)
        .add_image(10, "fjord.jpg", "raw/")
        .add_keyword_image(3, 10)
        .build()
    )
    kw = read_keywords(catalog_path)
    assert kw["raw/fjord.jpg"] == ["Places/Europe/Norway"]


def test_keywords_multiple_images(catalog_path: Path) -> None:
    (
        CatalogBuilder(catalog_path)
        .add_keyword(1, "nature")
        .add_image(10, "a.jpg", "raw/")
        .add_image(11, "b.jpg", "raw/")
        .add_keyword_image(1, 10)
        .add_keyword_image(1, 11)
        .build()
    )
    kw = read_keywords(catalog_path)
    assert kw["raw/a.jpg"] == ["nature"]
    assert kw["raw/b.jpg"] == ["nature"]


def test_no_keywords(catalog_path: Path) -> None:
    CatalogBuilder(catalog_path).add_image(1, "a.jpg", "raw/").build()
    assert read_keywords(catalog_path) == {}
