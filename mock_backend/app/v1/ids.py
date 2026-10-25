"""Stable UUIDs for the mock's slug ids (the v1 contract uses UUID strings).

`uid("team", "tarmo")` is always the same UUID; `slug("team", uuid)` maps it back. Incoming ids
may also be the old slugs, so links from the not-yet-migrated portal pages keep working.
"""

from uuid import NAMESPACE_URL, UUID, uuid5

_NS = uuid5(NAMESPACE_URL, "https://mock.oursport.local/")
_back: dict[tuple[str, str], str] = {}


def uid(kind: str, slug: str) -> str:
    value = str(uuid5(_NS, f"{kind}:{slug}"))
    _back[(kind, value)] = slug
    return value


def slug(kind: str, value: str) -> str:
    """The slug behind a UUID from `uid`, or the value itself (already a slug, or unknown)."""
    try:
        UUID(value)
    except ValueError:
        return value
    return _back.get((kind, value), value)
