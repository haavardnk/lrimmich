import pytest

from lrimmich.sync.keywords import desired_keyword_tags
from lrimmich.sync.tags import TagAssignments

RESOLVED = {"a.jpg": "a1", "b.jpg": "a2"}


@pytest.mark.parametrize(
    ("keywords", "prefix", "expected"),
    [
        (
            {"a.jpg": ["Travel", "Nature"], "b.jpg": ["Nature/Trees"]},
            "lr:keyword:",
            {
                "a1": ["lr:keyword:Nature", "lr:keyword:Travel"],
                "a2": ["lr:keyword:Nature/Trees"],
            },
        ),
        ({"a.jpg": ["Sea", "Sea"]}, "", {"a1": ["Sea"]}),
        ({"a.jpg": []}, "kw:", {}),
        ({"c.jpg": ["Sea"]}, "kw:", {}),
    ],
)
def test_desired_keyword_tags(
    keywords: dict[str, list[str]], prefix: str, expected: TagAssignments
) -> None:
    assert desired_keyword_tags(keywords, RESOLVED, prefix) == expected
