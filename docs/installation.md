---
layout: default
title: Installation
nav_order: 2
---

# Installation

## Requirements

- Python 3.11 or newer
- Immich 3.0 or newer, with an [API key](https://docs.immich.app/features/command-line-interface/#obtain-the-api-key)
- Your Lightroom Classic catalog (`.lrcat` file) accessible from the machine running lrimmich
- Photo files mounted in Immich as an external library

### Still on Immich 2.x?

Immich 3.0 renamed and removed fields lrimmich writes to. On 2.x, reject sync
silently does nothing and clearing a rating fails with an error from the server.
Stay on the lrimmich 0.2.x line until you upgrade Immich:

```
uv tool install "lrimmich<0.3"
```

## Install with uv (recommended)

```
uv tool install lrimmich
```

## Install with pipx

```
pipx install lrimmich
```

## Install with pip

```
pip install lrimmich
```

## Verify

```
lrimmich --version
```
