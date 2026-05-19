---
layout: default
title: Troubleshooting
nav_order: 8
---

# Troubleshooting

## Start with doctor

```
lrimmich doctor
```

This runs five checks and tells you exactly what's wrong. Always run it first.

## Common issues

### "Config not found"

Run `lrimmich config init` to create one, then `lrimmich config edit` to fill in your values.

### "No assets resolved"

The `library_paths` in your config doesn't match the folder structure Immich sees. Check that:

- The path matches exactly what Immich shows in Administration → External Libraries
- The folder hierarchy under that path mirrors your Lightroom catalog's folder layout
- If your LR paths have a prefix that doesn't exist in Immich, set `strip` in the `[[catalogs]]` entry to remove it

### "API key required"

Either set `immich.api_key` in the config file, or export `LRIMMICH_API_KEY` as an environment variable.

### "Catalog is locked" / WAL warning

Lightroom Classic has the catalog open. lrimmich reads the database in read-only mode, so this is usually fine — the warning is informational. If you get actual read errors, close Lightroom and try again.

### Albums are deleting too many assets

The safety config blocks runaway deletions. If you intentionally removed a lot of photos from a collection, either:

- Increase `safety.delete_threshold` or `safety.remove_percent_limit` temporarily
- Run with `--force` to bypass safety guards
- Run with `--no-delete` to skip all deletions

### Cached paths are stale

If photos were moved or deleted in Immich, the path cache might be out of date. Run:

```
lrimmich sync --refresh-cache
```

Or wait for the spot-check mechanism to catch it (checks 5% of cached entries by default each sync).

## Logs

Enable debug logging for more detail:

```
lrimmich --verbose sync
```

View recent sync activity:

```
lrimmich log
lrimmich log --limit 50
```

## Nuclear option

If state gets into a weird place, reset it:

```
lrimmich reset --force
```

The next sync rebuilds everything from scratch. No data in Immich is deleted by a reset — it only clears lrimmich's local tracking.
