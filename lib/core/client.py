import aiohttp
import orjson
import jwt

from .errors import *

__all__ = (
    "CoreClient",
)


class DataAccessor:
    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, item):
        res = self.inner.get(item)
        if type(res) in {dict, list}:
            return DataAccessor(res)
        else:
            return res

    def __getitem__(self, item):
        res = self.inner[item]
        if type(res) in {dict, list}:
            return DataAccessor(res)
        else:
            return res


class CoreClient:
    def __init__(self, session: aiohttp.ClientSession, base_url, jwt_secret):
        self.session = session
        self.base_url = base_url
        self._jwt_secret = jwt_secret

    async def request(self, method, path, **kwargs):
        headers = {}
        options = {}
        if "json" in kwargs:
            headers["Content-Type"] = "application/json"
            options["data"] = orjson.dumps(kwargs["json"])

        if "shard_hint" in kwargs:
            headers["X-Shard-Hint"] = kwargs["shard_hint"]

        if "user_id" in kwargs:
            headers["Authorization"] = jwt.encode({
                "tot": "i",
                "uid": str(kwargs["user_id"])
            }, self._jwt_secret)

        url = f"{self.base_url}/{path}"
        async with self.session.request(method, url, headers=headers, **options) as resp:
            raw = await resp.read()
            data = orjson.loads(raw)
            if data.get("success"):
                if type(data["data"]) in {dict, list}:
                    return DataAccessor(data["data"])
                else:
                    return data["data"]
            else:
                raise make_core_error(resp, data)

    def create_backup(self, user_id, guild_id):
        return self.request("POST", f"guilds/{guild_id}/backups", json={
            "flags": 0,
            "message_count": 0
        }, shard_hint=guild_id, user_id=user_id)
