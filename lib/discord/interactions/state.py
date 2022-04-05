import traceback

from ..utils import *
from datetime import datetime, timedelta
import asyncio

__all__ = (
    "StateStore",
)


class StateStore:
    def __init__(self):
        self.entries = {}

    def expire(self):
        now = datetime.utcnow()
        for key, (expires_at, _) in self.entries.items():
            if expires_at < now:
                self.entries.pop(key, None)

    async def expire_task(self):
        while True:
            await asyncio.sleep(5)
            try:
                self.expire()
            except:
                traceback.print_exc()

    def insert(self, data, expiry=60 * 5) -> str:
        identifier = unique_id()
        expires_at = datetime.utcnow() + timedelta(seconds=expiry)
        self.entries[identifier] = (expires_at, data)
        return identifier

    def get(self, identifier: str):
        entry = self.entries.get(identifier, None)
        if entry is not None:
            return entry[1]
        return None

    def pop(self, identifier: str):
        entry = self.entries.pop(identifier, None)
        if entry is not None:
            return entry[1]
        return None
