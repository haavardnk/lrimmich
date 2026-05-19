---
layout: default
title: Contributing
nav_order: 10
---

# Contributing

Bug reports and PRs are welcome. For bugs, include the output of `lrimmich doctor` and the command you ran.

[Open an issue on GitHub](https://github.com/haavardnk/lrimmich/issues)

## Dev setup

```
git clone https://github.com/haavardnk/lrimmich.git
cd lrimmich
uv sync
```

## Running tests

```
uv run pytest
```

## Linting and formatting

```
uv run ruff format src tests
uv run ruff check src tests --fix
```

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
feat: add album description sync
fix: handle empty collection gracefully
refactor: extract catalog queries
```

Subject line under 50 characters. Body only when the "why" isn't obvious from the subject.
