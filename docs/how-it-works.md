---
layout: default
title: How It Works
nav_order: 6
---

# How It Works

## Sync flow

1. **Read the catalog** — lrimmich opens the `.lrcat` SQLite database (read-only) and reads collections, picks, ratings, color labels, keywords, captions, and stack groupings.

2. **Resolve paths** — Lightroom stores file paths relative to the catalog root folders. lrimmich maps these to Immich asset IDs by scanning the external library folder tree via the Immich API. Resolved mappings are cached locally so repeat syncs skip the API calls. The cache has a configurable TTL and spot-check percentage (see [cache config](configuration#cache)).

3. **Diff against last sync** — lrimmich keeps a fingerprint of the catalog state. If nothing changed since the last sync, it exits early. When something did change, it computes the diff for each sync domain (albums, favorites, ratings, etc.) and applies only the delta.

4. **Apply changes** — Creates, updates, and deletes albums; sets and clears favorites, ratings, tags, captions, and stacks through the Immich API. Safety guards prevent runaway deletions.

5. **Record state** — The sync result is written to the local state database so the next run can diff against it.

## Album modes

### Managed (default)

Lightroom fully controls album contents. If an asset exists in an Immich album but isn't in the matching Lightroom collection, it gets removed on sync. This keeps albums as exact mirrors of your Lightroom collections.

### Hybrid

Set `album_mode = "hybrid"` under `[sync]`. In this mode, lrimmich tracks which assets it placed in each album and only removes those when they disappear from the Lightroom collection. Assets added manually inside Immich are left alone.

This is useful when you want to add photos to albums from Immich's UI (mobile uploads, shared library, etc.) without lrimmich removing them on the next sync.

## Album filters and rules

Album membership can be filtered globally or per collection:

- `album_filter = "flagged"` — only flagged photos go into albums
- `album_filter = "unflagged"` — exclude rejects
- `album_min_rating = 3` — only 3+ star photos

Per-collection overrides use `[[album_rules]]` entries. First matching rule wins. You can match by collection path glob or by collection ID. See [Configuration](configuration#album_rules) for the full syntax.

## Fingerprint and incremental syncs

The catalog fingerprint is a hash of the collection structure and image metadata. When the fingerprint hasn't changed since the last sync, lrimmich skips all API work and exits immediately. Use `--force` to bypass this check.

## Path cache

Resolving file paths against the Immich API is the slowest part of a sync. lrimmich caches the mapping from relative path to asset ID in a local SQLite database. The cache expires after `cache.ttl_days` (default 90). Each sync also spot-checks a random sample of cached entries (`cache.spot_check_pct`, default 5%) to catch files that moved or were deleted in Immich.

Use `--refresh-cache` to force a full re-resolution.
