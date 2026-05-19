---
layout: default
title: Home
nav_order: 1
---

# lrimmich

Syncs your Lightroom Classic catalog to Immich. Collections become albums, picks become favorites, rejects get archived, ratings carry over, and color labels and keywords are written as tags.

The same photo files Lightroom reads must be mounted into Immich as an external library. lrimmich doesn't upload anything — it matches files already present on both sides and writes metadata through the Immich API.

## Quick start

```
uv tool install lrimmich
lrimmich config init
lrimmich doctor
lrimmich sync --dry-run
```

See [Installation](installation) and [Getting Started](getting-started) for the full walkthrough.

## What gets synced

| Lightroom | Immich |
|-----------|--------|
| Collections | Albums |
| Picks | Favorites |
| Rejects | Archived |
| Star ratings | Ratings |
| Color labels | Color tags |
| Keywords | Keyword tags |
| Captions | Asset descriptions |
| Stacks | Stacks |
