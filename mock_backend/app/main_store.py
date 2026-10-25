"""The one in-memory store, shared by the old routes (main.py) and the v1 contract (v1/)."""

from .store import FeedStore

store = FeedStore()
