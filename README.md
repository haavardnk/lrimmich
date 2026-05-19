# lrimmich

[![PyPI](https://img.shields.io/pypi/v/lrimmich)](https://pypi.org/project/lrimmich/)
[![Docs](https://img.shields.io/badge/docs-haavardnk.github.io%2Flrimmich-blue)](https://haavardnk.github.io/lrimmich/)

Syncs your Lightroom Classic catalog to Immich. Collections become albums, picks become favorites, rejects become archived, ratings carry over, and color labels and keywords are written as tags.

The same photo files Lightroom reads must be mounted into Immich as an external library. lrimmich doesn't upload anything. It matches files that are already on both sides and writes metadata through the Immich API.

## Quick start

```
uv tool install lrimmich
lrimmich config init
lrimmich doctor
lrimmich sync --dry-run
```

See the [full documentation](https://haavardnk.github.io/lrimmich/) for configuration, commands, and how it all works.

## License

MIT
