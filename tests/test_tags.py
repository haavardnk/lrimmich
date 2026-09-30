import pytest

from lrimmich.sync.summary import TagSyncResult
from lrimmich.sync.tags import TagAction, TagAssignments, TagPlan, diff_tags


@pytest.mark.parametrize(
    ("previous", "desired", "existing", "expected"),
    [
        ({}, {"a1": ["x"], "a2": ["x"]}, set(), [("tag", "x", ["a1", "a2"])]),
        ({"a1": ["x"]}, {"a1": ["x"]}, {"x"}, []),
        (
            {"a1": ["x"]},
            {"a1": ["y"]},
            {"x"},
            [("tag", "y", ["a1"]), ("untag", "x", ["a1"])],
        ),
        ({"a1": ["x", "y"]}, {"a1": ["x"]}, {"x", "y"}, [("untag", "y", ["a1"])]),
        ({"a1": ["x"]}, {}, {"x"}, [("untag", "x", ["a1"])]),
        ({"a1": ["x"]}, {}, set(), []),
        (
            {"a1": ["old:x"]},
            {"a1": ["new:x"]},
            {"old:x"},
            [("tag", "new:x", ["a1"]), ("untag", "old:x", ["a1"])],
        ),
    ],
)
def test_diff_tags(
    previous: TagAssignments,
    desired: TagAssignments,
    existing: set[str],
    expected: list[tuple[str, str, list[str]]],
) -> None:
    actions = diff_tags(previous, desired, existing)
    assert [(a.kind, a.tag_name, a.asset_ids) for a in actions] == expected


def test_plan_result_counts_assets() -> None:
    plan = TagPlan(
        [
            TagAction("tag", "x", ["a1", "a2"]),
            TagAction("tag", "y", ["a1"]),
            TagAction("untag", "z", ["a3"]),
        ],
        {},
    )
    assert plan.result == TagSyncResult(tagged=3, untagged=1)
