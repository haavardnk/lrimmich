---
layout: default
title: Configuration
nav_order: 4
---

# Configuration

The config file is TOML. Run `lrimmich config init` to generate one, or `lrimmich config show` to see the resolved values (secrets redacted). Unknown keys are rejected, so a misspelled option stops every command with an error naming the key.

## Full example

Every setting at its default value. Only `[[catalogs]]` and `[immich]` are required; omitted keys take the defaults shown here. Commented lines are optional settings with no default; the `[[album_rules]]` block shows one example rule.

```toml
[[catalogs]]
catalog = "~/Pictures/Lightroom/Lightroom.lrcat"
# strip = "raw/"
exclude_collections = []
exclude_patterns = []

[immich]
url = "http://localhost:2283"
api_key = "your-api-key-here"
library_paths = ["/external/images/"]

[sync]
albums = true
favorites = true
ratings = true
tags = true
captions = true
rejects = false
stacks = false
scope = "collections"
skip_empty = true
album_mode = "managed"
album_filter = "all"
album_min_rating = 0
album_name_format = "{path}"
keyword_prefix = "lr:keyword:"
color_prefix = "lr:color:"
reject_mode = "archive"
reject_tag = "lr:reject"
share_albums_with = []

[sync.color_tags]
# red = "portfolio"

[cache]
ttl_days = 90
spot_check_pct = 5
miss_ttl_minutes = 60

# [[album_rules]]
# match = "Travel/*"
# filter = "flagged"
# min_rating = 3
# description = "Travel photos from trips"
# order = "desc"
# share_with = ["user-uuid-here"]

[safety]
delete_threshold = 100
remove_percent_limit = 50
disable_deletes = false

[notification]
# url = "https://ntfy.sh/your-topic"
```

## `[[catalogs]]`

Each `[[catalogs]]` entry defines a Lightroom catalog to sync. Add multiple entries to sync multiple catalogs into the same Immich server.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `catalog` | string | *required* | Path to your `.lrcat` file. Tilde expansion is supported. |
| `strip` | string \| null | `null` | Prefix to strip from Lightroom-relative paths before matching against Immich. Useful when your Lightroom folder structure has a prefix that doesn't exist in the external library mount. |
| `exclude_collections` | list[int] | `[]` | Collection or collection set IDs to skip. Find IDs via `lrimmich collections`. |
| `exclude_patterns` | list[string] | `[]` | Glob patterns matched against the full collection path, e.g. `"Exports/*"` or `"*/WIP"`. |

Example with two catalogs:

```toml
[[catalogs]]
catalog = "~/Pictures/Personal/Personal.lrcat"

[[catalogs]]
catalog = "~/Pictures/Work/Work.lrcat"
strip = "raw/"
exclude_patterns = ["Exports/*"]
```

## `[immich]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `url` | string | *required* | Immich server URL, e.g. `http://localhost:2283`. |
| `api_key` | string | `""` | Immich API key. Can also be set via the `LRIMMICH_API_KEY` environment variable, which takes precedence. Generate one at Immich → Account Settings → API Keys. |
| `library_paths` | list[string] | *required* | External library paths where your photos are stored. The folder structure must mirror your Lightroom catalog's folder layout. |

## `[sync]`

### Feature toggles

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `albums` | bool | `true` | Sync collections as albums. |
| `favorites` | bool | `true` | Sync picks as favorites. |
| `ratings` | bool | `true` | Sync star ratings to Immich ratings. |
| `tags` | bool | `true` | Sync color labels and keywords as tags. |
| `captions` | bool | `true` | Sync captions as asset descriptions. |
| `rejects` | bool | `false` | Sync rejects, as set by `reject_mode`. |
| `stacks` | bool | `false` | Sync Lightroom stacks to Immich stacks (top image becomes primary). |

### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `scope` | `"collections"` \| `"all"` | `"collections"` | `"collections"` syncs metadata only for assets in synced collections. `"all"` also resolves images outside collections and syncs metadata for every image in the catalog. |
| `skip_empty` | bool | `true` | Skip creating albums for collections with no resolved assets. |

### Album settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `album_mode` | `"managed"` \| `"hybrid"` | `"managed"` | `"managed"` means Lightroom fully controls album contents — assets not in the matching collection get removed. `"hybrid"` preserves assets added manually in Immich. See [How It Works](how-it-works#album-modes). |
| `album_filter` | `"all"` \| `"flagged"` \| `"unflagged"` \| `"rejected"` | `"all"` | Global album membership filter. |
| `album_min_rating` | int (0–5) | `0` | Minimum star rating for album membership. 0 disables the filter. |
| `album_name_format` | string | `"{path}"` | Album naming format. Placeholders: `{path}` (full hierarchy), `{name}` (leaf collection name), `{parent}` (parent set name). |

### Tag prefixes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `keyword_prefix` | string | `"lr:keyword:"` | Prefix for synced keyword tags. Set to `""` to sync without a prefix. |
| `color_prefix` | string | `"lr:color:"` | Prefix for synced color label tags. Set to `""` to sync without a prefix. |
| `color_tags` | table | `{}` | Tag name to use per Lightroom color label, replacing the default lowercase color name. Keys match label names case-insensitively. The prefix is still added. |
| `reject_mode` | `"archive"` \| `"tag"` | `"archive"` | Archive rejects, or tag them with `reject_tag`. |
| `reject_tag` | string | `"lr:reject"` | Tag for rejects when `reject_mode = "tag"`. |
| `share_albums_with` | list[string] | `[]` | Immich user IDs to share every synced album with. Overridable per album rule. |

By default the labels Red, Yellow, Green, Blue, and Purple become `red`, `yellow`, `green`, `blue`, and `purple`. Labels with any other name are skipped unless they appear in `color_tags`, so a custom Lightroom label set can be synced by listing its names:

```toml
[sync.color_tags]
red = "portfolio"
"To Print" = "print"
```

Changing a name or a prefix moves the tag on the next sync: assets lose the old tag and get the new one. The old tag itself stays in Immich, empty.

Changing `reject_mode` moves rejects the same way: rejects lrimmich archived are unarchived and tagged, or untagged and archived. Changing `reject_tag` moves the tag.

A `/` in a tag name nests it in Immich's tag tree. To share color labels and rejects with [immich-edit](https://github.com/haavardnk/immich-edit):

```toml
[sync]
rejects = true
color_prefix = "immich-edit/label/"
reject_mode = "tag"
reject_tag = "immich-edit/reject"
```

## `[cache]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `ttl_days` | int (≥1) | `90` | Days before cached path-to-asset mappings expire. |
| `spot_check_pct` | int (0–100) | `5` | Percentage of cached entries to verify against Immich each sync. Set to 0 to disable. |
| `miss_ttl_minutes` | int (≥0) | `60` | Minutes to remember that a photo isn't in Immich yet, so repeat syncs skip the folder crawl. Set to 0 to look every time. |

## `[[album_rules]]`

Per-collection overrides for album membership. First matching rule wins.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `match` | string \| null | `null` | Glob pattern matched against the collection path, e.g. `"Travel/*"`. |
| `id` | int \| null | `null` | Match a specific collection by ID instead of path. |
| `filter` | string \| null | `null` | Override `album_filter` for matched collections. |
| `min_rating` | int \| null | `null` | Override `album_min_rating` for matched collections. |
| `description` | string \| null | `null` | Set the Immich album description. |
| `order` | `"asc"` \| `"desc"` \| null | `null` | Asset sort order within the album. |
| `share_with` | list[string] \| null | `null` | Override `share_albums_with` for matched collections. |

Example:

```toml
[[album_rules]]
match = "Travel/*"
filter = "flagged"
min_rating = 3
description = "Travel photos from trips"
order = "desc"

[[album_rules]]
id = 1284922
filter = "unflagged"
```

## `[safety]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `delete_threshold` | int | `100` | Block album deletion when more than this many albums would be removed in one sync. |
| `remove_percent_limit` | int | `50` | Block asset removal when it exceeds this percentage of an album's current assets. |
| `disable_deletes` | bool | `false` | Never delete albums, regardless of other settings. |

## `[notification]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `url` | string \| null | `null` | Webhook URL to POST sync summaries to. Leave empty to disable. Compatible with ntfy, Apprise, or any service that accepts a JSON POST. |
