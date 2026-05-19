---
layout: default
title: Watch & Service
nav_order: 7
---

# Watch & Service

## Watch mode

Watches the catalog file (and its WAL journal) for filesystem changes. When a change is detected, lrimmich waits for a debounce window to pass (in case Lightroom is still writing), then runs a sync.

```
lrimmich watch
lrimmich watch --debounce 10000
```

The default debounce is 5 seconds. Increase it if your catalog is large or Lightroom writes take a while to settle.

Watch mode runs in the foreground. Use `Ctrl+C` to stop it.

## Background service

To run syncs on a fixed schedule (without needing to keep a terminal open), generate a system service:

### macOS (launchd)

```
lrimmich install-service --interval 300
```

This creates a launchd plist at `~/Library/LaunchAgents/com.lrimmich.sync.plist` that runs `lrimmich sync` every 5 minutes. The service starts immediately and loads on login.

### Linux (systemd)

```
lrimmich install-service --interval 300
```

This creates a systemd user timer and service unit. Enable and start it with the commands printed after install.

### Preview without installing

```
lrimmich install-service --dry-run
```

Prints the unit file contents without writing anything.

### Uninstall

```
lrimmich uninstall-service
```

Removes the generated service files.
