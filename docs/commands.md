---
layout: default
title: Commands
nav_order: 5
---

# Commands

All commands support `--help` for detailed flag info.

## `sync`

Run a full sync from Lightroom to Immich.

```
lrimmich sync
lrimmich sync --dry-run
lrimmich sync --dry-run --interactive
lrimmich sync --force --no-delete
lrimmich sync --json --quiet
```

| Flag | Description |
|------|-------------|
| `--config`, `-c` | Config file path (default: platform config dir) |
| `--dry-run` | Preview changes without applying them |
| `--force` | Skip safety guards and fingerprint cache |
| `--interactive`, `-i` | Prompt before each sync step (useful with `--dry-run`) |
| `--json` | Output the sync summary as JSON |
| `--quiet`, `-q` | Suppress output |
| `--no-delete` | Skip all album and asset deletions |
| `--notify-on-drift` | Send a notification only if something changed |
| `--refresh-cache` | Ignore cached path resolutions, re-resolve everything |

## `status`

Check for drift between Lightroom and Immich. Exits with code 1 if anything is out of sync — useful in scripts and CI.

```
lrimmich status
lrimmich status --json
```

## `doctor`

Verify config, connectivity, API permissions, and path mapping.

```
lrimmich doctor
```

Checks:
1. Catalog file opens and is readable
2. Lightroom WAL lock (detects if LR is open)
3. Immich API is reachable
4. API key has required permissions
5. At least one file path resolves between the two systems

## `watch`

Watch the catalog file (including WAL) for filesystem changes and auto-sync after a debounce window.

```
lrimmich watch
lrimmich watch --debounce 5000
```

| Flag | Description |
|------|-------------|
| `--debounce` | Milliseconds to wait after last change before syncing (default: 5000) |
| `--force` | Skip safety guards on each sync |
| `--no-delete` | Skip deletions on each sync |
| `--quiet`, `-q` | Suppress output |

## `adopt`

Find existing Immich albums that match Lightroom collection names and claim them so lrimmich manages them going forward.

```
lrimmich adopt           # preview matches
lrimmich adopt --apply   # write the mappings
```

## `log`

Show recent sync activity from the audit log.

```
lrimmich log
lrimmich log --limit 50
lrimmich log --json
```

## `collections`

List catalog collections with their IDs. Useful for finding IDs to exclude or write album rules for.

```
lrimmich collections
lrimmich collections --json
```

## `reset`

Delete the state database. The next sync rebuilds everything from scratch.

```
lrimmich reset           # prompts for confirmation
lrimmich reset --force   # no prompt
```

## `install-service`

Generate a launchd plist (macOS) or systemd unit (Linux) that runs `lrimmich sync` on a schedule.

```
lrimmich install-service
lrimmich install-service --interval 300
```

| Flag | Description |
|------|-------------|
| `--interval` | Seconds between syncs (default: 300) |
| `--dry-run` | Print the unit file without installing it |

## `uninstall-service`

Remove the generated service files.

```
lrimmich uninstall-service
```

## `config init`

Write a starter config file with all options documented.

```
lrimmich config init
```

## `config show`

Print the resolved config with secrets redacted.

```
lrimmich config show
```

## `config edit`

Open the config file in your default editor (`$EDITOR`).

```
lrimmich config edit
```

## `docs`

Open the documentation in your browser.

```
lrimmich docs
```

## Global flags

| Flag | Description |
|------|-------------|
| `--version`, `-V` | Print version and exit |
| `--verbose`, `-v` | Enable debug logging |
