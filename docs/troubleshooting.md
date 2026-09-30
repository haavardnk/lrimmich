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

This runs a series of checks and tells you exactly what's wrong. Always run it first.

## Common issues

### Rejects aren't archived, or clearing a rating fails

Your Immich server is older than 3.0. Version 3.0 renamed the archive field and
stopped accepting a rating of zero, and lrimmich now targets the newer API.
Upgrade Immich, or stay on the lrimmich 0.2.x line, which speaks the 2.x API.
`doctor` reports the version it detected, so check there if you're unsure.

### A sync step failed with an Immich error

Errors from Immich include the server's own response body, so the message names
the field it rejected. Run `lrimmich --verbose sync` for the full request trace.

### "Immich server unreachable"

lrimmich couldn't connect to `immich.url`, or the server didn't answer within
30 seconds. Check that Immich is running and that the URL is right. The sync
stops there, and the next successful run finishes the rest.

### "Config not found"

Run `lrimmich config init` to create one, then `lrimmich config edit` to fill in your values.

### "No assets resolved"

The `library_paths` in your config doesn't match the folder structure Immich sees. Check that:

- The path matches exactly what Immich shows in Administration → External Libraries
- The folder hierarchy under that path mirrors your Lightroom catalog's folder layout
- If your LR paths have a prefix that doesn't exist in Immich, set `strip` in the `[[catalogs]]` entry to remove it

`lrimmich doctor` prints the exact path it looked for, which usually makes the
mismatch obvious.

### Sync reports unresolved photos

The summary line `unresolved: N photo(s) in Lightroom were not found in Immich`
means those files exist in your catalog but Immich has no asset at the mapped
path. Usually they simply haven't been uploaded or scanned yet. If the number is
larger than you expect, check `library_paths` and `strip` as above.

### "API key required"

Either set `immich.api_key` in the config file, or export `LRIMMICH_API_KEY` as an environment variable.

### "Catalog is locked" / WAL warning

Lightroom Classic has the catalog open and is holding a write lock, so edits made
in this session may not be visible yet. Close Lightroom and sync again to pick
them up.

### "Catalog unchanged" right after an import

If `lrimmich watch` or the background service is running, it has probably
synced the changes already. `lrimmich log` shows what it did.

### Moving photos between collections didn't sync

Older versions missed this: the fingerprint only counted membership rows, and
moving a photo from one collection to another leaves the count identical, so the
sync exited early. Upgrade, or run `lrimmich sync --force` on an old version.

### "Immich album(s) match collection names but are not tracked"

Immich already has albums named like your Lightroom collections, and lrimmich
won't touch albums it didn't create. Preview the matches with
`lrimmich sync --adopt-existing --dry-run`, then run
`lrimmich sync --adopt-existing` to claim them.

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
