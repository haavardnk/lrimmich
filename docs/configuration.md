---
layout: default
title: Configuration
nav_order: 4
---

# Configuration

The config file is TOML. Run `lrimmich config init` to generate one, or `lrimmich config show` to see the resolved values (secrets redacted).

## `[lightroom]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `catalog` | string | *required* | Path to your `.lrcat` file. Tilde expansion is supported. |
| `strip` | string | `""` | Prefix to strip from Lightroom-relative paths before matching against Immich. Useful when your Lightroom folder structure has a prefix that doesn't exist in the external library mount. |

## `[immich]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `url` | string | *required* | Immich server URL, e.g. `http://localhost:2283`. |
| `api_key` | string | `""` | Immich API key. Can also be set via the `LRIMMICH_API_KEY` environment variable, which takes precedence. Generate one at Immich → Account Settings → API Keys. |
| `library_path` | string | *required* | External library path where your photos are stored. The folder structure must mirror your Lightroom catalog's folder layout. |
| `share_albums_with` | list[string] | `[]` | Immich user IDs to share every synced album with. |

## `[exclude]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `collection_ids` | list[int] | `[]` | Collection or collection set IDs to skip. Find IDs via `lrimmich collections`. |
| `name_patterns` | list[string] | `[]` | Glob patterns matched against the full collection path, e.g. `"Exports/*"` or `"*/WIP"`. |

## `[sync]`

### Feature toggles

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `albums` | bool | `true` | Sync collections as albums. |
| `favorites` | bool | `true` | Sync picks as favorites. |
| `ratings` | bool | `true` | Sync star ratings as tags. |
| `tags` | bool | `true` | Sync color labels and keywords as tags. |
| `captions` | bool | `true` | Sync captions as asset descriptions. |
| `rejects` | bool | `false` | Sync rejects as archived. |
| `stacks` | bool | `false` | Sync Lightroom stacks to Immich stacks (first image becomes primary). |

### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `scope` | `"collections"` \| `"all"` | `"collections"` | `"collections"` syncs metadata only for assets in synced collections. `"all"` syncs metadata for every resolved asset in the catalog. |
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
| `keyword_prefix` | string | `"lr:keyword:"` | Prefix for synced keyword tags. |
| `color_prefix` | string | `"lr:color:"` | Prefix for synced color label tags. |

## `[cache]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `ttl_days` | int (≥1) | `90` | Days before cached path-to-asset mappings expire. |
| `spot_check_pct` | int (0–100) | `5` | Percentage of cached entries to verify against Immich each sync. Set to 0 to disable. |

## `[[album_rules]]`

Per-collection overrides for album membership. First matching rule wins.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `match` | string | `""` | Glob pattern matched against the collection path, e.g. `"Travel/*"`. |
| `id` | int \| null | `null` | Match a specific collection by ID instead of path. |
| `filter` | string \| null | `null` | Override `album_filter` for matched collections. |
| `min_rating` | int \| null | `null` | Override `album_min_rating` for matched collections. |
| `description` | string \| null | `null` | Set the Immich album description. |
| `order` | `"asc"` \| `"desc"` \| null | `null` | Asset sort order within the album. |

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
| `url` | string | `""` | Webhook URL to POST sync summaries to. Leave empty to disable. Compatible with ntfy, Apprise, or any service that accepts a JSON POST. |
