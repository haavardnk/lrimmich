from lrimmich.clients.catalog import read_color_labels
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import SyncSummary
from lrimmich.sync.tags import TagAssignments, TagPlan, apply_tags, plan_tags
from lrimmich.utils.config import Config

DEFAULT_COLORS = ("red", "yellow", "green", "blue", "purple")
SNAPSHOT_KEY = "color_labels_snapshot"


def desired_color_tags(
    labels: dict[str, str],
    resolved: dict[str, str],
    overrides: dict[str, str],
    prefix: str,
) -> TagAssignments:
    names = {c: c for c in DEFAULT_COLORS} | {
        label.lower(): tag for label, tag in overrides.items()
    }
    return {
        resolved[rp]: [prefix + names[label.lower()]]
        for rp, label in labels.items()
        if rp in resolved and label.lower() in names
    }


class Step:
    name = "color_labels"
    status_msg = "Syncing color labels..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.tags

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> TagPlan:
        desired = desired_color_tags(
            read_color_labels(ctx.catalog.catalog),
            ctx.resolved,
            ctx.cfg.sync.color_tags,
            ctx.cfg.sync.color_prefix or "",
        )
        plan = await plan_tags(ctx, desired, SNAPSHOT_KEY)
        summary.color_labels = plan.result
        return plan

    async def apply(self, plan: TagPlan, ctx: SyncContext) -> None:
        await apply_tags(ctx, plan, SNAPSHOT_KEY, "sync_color_labels")
