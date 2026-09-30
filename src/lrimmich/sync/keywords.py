from lrimmich.clients.catalog import read_keywords
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import SyncSummary
from lrimmich.sync.tags import TagAssignments, TagPlan, apply_tags, plan_tags
from lrimmich.utils.config import Config

SNAPSHOT_KEY = "keywords_snapshot"


def desired_keyword_tags(
    keywords: dict[str, list[str]], resolved: dict[str, str], prefix: str
) -> TagAssignments:
    return {
        resolved[rp]: sorted({prefix + k for k in kws})
        for rp, kws in keywords.items()
        if rp in resolved and kws
    }


class Step:
    name = "keywords"
    status_msg = "Syncing keywords..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.tags

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> TagPlan:
        desired = desired_keyword_tags(
            read_keywords(ctx.catalog.catalog),
            ctx.resolved,
            ctx.cfg.sync.keyword_prefix or "",
        )
        plan = await plan_tags(ctx, desired, SNAPSHOT_KEY)
        summary.keywords = plan.result
        return plan

    async def apply(self, plan: TagPlan, ctx: SyncContext) -> None:
        await apply_tags(ctx, plan, SNAPSHOT_KEY, "sync_keywords")
