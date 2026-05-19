---
layout: default
title: Getting Started
nav_order: 3
---

# Getting Started

## 1. Create a config file

```
lrimmich config init
```

This writes a starter config to your platform's user config directory:

| OS | Path |
|----|------|
| Linux | `~/.config/lrimmich/config.toml` (XDG) |
| macOS | `~/Library/Application Support/lrimmich/config.toml` |
| Windows | `%APPDATA%\lrimmich\config.toml` |

Open it in your editor:

```
lrimmich config edit
```

Fill in at minimum:

- `catalogs` — at least one `[[catalogs]]` entry with a `catalog` path to your `.lrcat` file
- `immich.url` — your Immich server URL
- `immich.api_key` — an Immich API key (or set `LRIMMICH_API_KEY` env var instead)
- `immich.library_paths` — the external library paths in Immich where your photos live

See [Configuration](configuration) for every available option.

## 2. Run the doctor

```
lrimmich doctor
```

This checks that the catalog opens, the Immich API responds, your API key has the right permissions, and at least one file path resolves between the two systems. Fix anything it flags before continuing.

## 3. Preview changes

```
lrimmich sync --dry-run
```

Shows what would happen without actually touching anything. Review the output to make sure album names, asset counts, and metadata look right.

## 4. Sync

```
lrimmich sync
```

That's it. Repeat runs only touch what changed since the last sync.
