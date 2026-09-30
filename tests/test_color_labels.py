import pytest

from lrimmich.sync.color_labels import desired_color_tags
from lrimmich.sync.tags import TagAssignments


@pytest.mark.parametrize(
    ("label", "overrides", "prefix", "expected"),
    [
        ("Red", {}, "lr:color:", {"a1": ["lr:color:red"]}),
        ("Red", {"red": "Portfolio"}, "", {"a1": ["Portfolio"]}),
        ("Red", {"RED": "Portfolio"}, "c:", {"a1": ["c:Portfolio"]}),
        ("Blue", {"red": "Portfolio"}, "", {"a1": ["blue"]}),
        ("To Print", {}, "", {}),
        ("To Print", {"to print": "print"}, "", {"a1": ["print"]}),
    ],
)
def test_desired_color_tags(
    label: str, overrides: dict[str, str], prefix: str, expected: TagAssignments
) -> None:
    resolved = {"a.jpg": "a1", "b.jpg": "a2"}
    assert desired_color_tags({"a.jpg": label}, resolved, overrides, prefix) == expected


def test_desired_color_tags_skips_unresolved() -> None:
    assert desired_color_tags({"a.jpg": "Red"}, {}, {}, "") == {}
