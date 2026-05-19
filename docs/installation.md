---
layout: default
title: Installation
nav_order: 2
---

# Installation

## Requirements

- Python 3.11 or newer
- A running Immich instance with an [API key](https://docs.immich.app/features/command-line-interface/#obtain-the-api-key)
- Your Lightroom Classic catalog (`.lrcat` file) accessible from the machine running lrimmich
- Photo files mounted in Immich as an external library

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
