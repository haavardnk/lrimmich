# lrimmich

[![PyPI](https://img.shields.io/pypi/v/lrimmich)](https://pypi.org/project/lrimmich/)

Syncs your Lightroom Classic catalog to Immich. Collections become albums, picks become favorites, rejects become archived, ratings carry over, and color labels and keywords are written as tags.

The same photo files Lightroom reads must be mounted into Immich as an external library. lrimmich doesn't upload anything. It matches files that are already on both sides and writes metadata through the Immich API.

## Install

```
uv tool install lrimmich
```

or `pipx install lrimmich`.

## Getting started

```
lrimmich config init
```

This writes a starter config to your platform's user config directory:

- Linux: `~/.config/lrimmich/config.toml` (XDG)
- macOS: `~/Library/Application Support/lrimmich/config.toml`
- Windows: `%APPDATA%\lrimmich\config.toml`

Fill in your Lightroom Classic catalog path, Immich URL, [API key](https://docs.immich.app/features/command-line-interface/#obtain-the-api-key), and external library path. If you prefer not to store the API key in the file, set `LRIMMICH_API_KEY` as an environment variable instead. Run `lrimmich config edit` to open the file in your editor, or see [sample_config.toml](src/lrimmich/utils/sample_config.toml) for all options.

```
lrimmich doctor
```

Checks that the catalog opens, the Immich API responds, and file paths match between the two. If it passes, run a dry-run first:

```
lrimmich sync --dry-run
```

## Commands

```
lrimmich sync              # sync everything
lrimmich sync --dry-run    # see what would happen
lrimmich status            # check for drift (exit 1 if out of sync)
lrimmich doctor            # verify config, connectivity, and path mapping
lrimmich watch             # watch for catalog changes, sync when detected
lrimmich adopt             # claim existing Immich albums by name match
lrimmich log               # show recent sync activity
lrimmich collections       # list catalog collections with IDs
lrimmich reset             # delete state DB, next sync rebuilds from scratch
lrimmich install-service   # generate launchd/systemd unit (macOS/Linux)
lrimmich uninstall-service # remove service files (macOS/Linux)
lrimmich config show       # print resolved config (secrets redacted)
lrimmich config edit       # open config in your default editor
```

### Watch

Watches the catalog file (including WAL) for filesystem changes and syncs after a debounce window:

```
lrimmich watch --debounce 5000
```

To run it as a background service:

```
lrimmich install-service --interval 300
```

## How it works

Reads the `.lrcat` SQLite database, maps LR file paths to Immich asset IDs by scanning the external library folder tree, then diffs against what was synced last time (stored alongside the config in your platform's user state directory). Repeat runs only touch what changed.

### Album modes

By default albums run in **managed** mode — Lightroom fully controls album contents. Any asset in Immich that isn't in the matching Lightroom collection gets removed on sync.

Set `album_mode = "hybrid"` under `[sync]` to let users add extra photos to albums inside Immich without them being removed. In hybrid mode lrimmich tracks which assets it placed and only removes those when they disappear from the Lightroom collection. Manually-added Immich assets are left untouched.

Album membership can also be filtered globally or per collection. Use `album_filter = "flagged"` to create albums from Lightroom flagged photos only, `"unflagged"` to exclude rejects, or `album_min_rating = 3` for 3+ star albums. Add `[[album_rules]]` entries to override the filter for specific collection paths or IDs.

## Alternatives

| | How it works | Uploads photos? |
|---|---|---|
| **lrimmich** | CLI tool. Reads the .lrcat database directly, matches files already mounted in Immich, writes metadata only. | No |
| [immich-go](https://github.com/simulot/immich-go) | CLI tool. Bulk uploads from local folders, Google Photos takeouts, iCloud exports. Handles duplicates and stacking. | Yes |
| [lrc-immich-plugin](https://github.com/bmachek/lrc-immich-plugin) | LR Classic plugin. Export and publish service that uploads rendered photos via the Immich API. Can also import from Immich. | Yes |
| [mi.Immich.Publisher](https://github.com/midzelis/mi.Immich.Publisher) | LR Classic plugin. Publishes collections as albums, deduplicates across collections. Beta, not actively maintained. | Yes |

## Contributing

Bug reports and PRs welcome. For bugs, include the output of `lrimmich doctor` and the command you ran. Open an issue at [github.com/haavardnk/lrimmich/issues](https://github.com/haavardnk/lrimmich/issues).

## License

MIT
