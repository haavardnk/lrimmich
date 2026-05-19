---
layout: default
title: Alternatives
nav_order: 9
---

# Alternatives

| | How it works | Uploads photos? |
|---|---|---|
| **lrimmich** | CLI tool. Reads the .lrcat database directly, matches files already mounted in Immich, writes metadata only. | No |
| [immich-go](https://github.com/simulot/immich-go) | CLI tool. Bulk uploads from local folders, Google Photos takeouts, iCloud exports. Handles duplicates and stacking. | Yes |
| [lrc-immich-plugin](https://github.com/bmachek/lrc-immich-plugin) | LR Classic plugin. Export and publish service that uploads rendered photos via the Immich API. Can also import from Immich. | Yes |
| [mi.Immich.Publisher](https://github.com/midzelis/mi.Immich.Publisher) | LR Classic plugin. Publishes collections as albums, deduplicates across collections. | Yes |

The main difference: lrimmich never uploads photos. Your files need to already be in Immich via an external library mount. The other tools handle the upload step too, but don't read Lightroom's catalog database directly for metadata sync.
