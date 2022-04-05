import aiohttp
import jwt
import orjson

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

    def __iter__(self):
        if type(self.inner) == dict:
            for key, value in self.inner.items():
                yield key, DataAccessor(value)
        else:
            for item in self.inner:
                if type(item) in {dict, list}:
                    yield DataAccessor(item)
                else:
                    yield item


class CoreClient:
    def __init__(self, session: aiohttp.ClientSession, base_url, jwt_secret):
        self.session = session
        self.base_url = base_url
        self._jwt_secret = jwt_secret

    async def request(self, method, path, parse=True, **kwargs):
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

        if "params" in kwargs:
            options["params"] = kwargs["params"]

        url = f"{self.base_url}/{path}"
        async with self.session.request(method, url, headers=headers, **options) as resp:
            if not parse:
                return resp

            raw = await resp.read()
            data = orjson.loads(raw)
            if data.get("success"):
                if type(data["data"]) in {dict, list}:
                    return DataAccessor(data["data"])
                else:
                    return data["data"]
            else:
                raise make_core_error(resp, data)

    def backup_create(self, user_id, guild_id):
        return self.request("POST", f"guilds/{guild_id}/backups", json={
            "flags": 0,
            "message_count": 0
        }, shard_hint=guild_id, user_id=user_id)

    def backup_load(self, user_id, guild_id, backup_id):
        return self.request("POST", f"guilds/{guild_id}/backups/{backup_id}", json={
            "flags": 0,
            "message_count": 0
        }, shard_hint=guild_id, user_id=user_id)

    def backup_delete(self, user_id, backup_id):
        return self.request("DELETE", f"backups/{backup_id}", user_id=user_id)

    def backup_delete_all(self, user_id):
        return self.request("DELETE", f"backups", user_id=user_id)

    async def backup_exists(self, user_id, backup_id):
        resp = await self.request("HEAD", f"backups/{backup_id}", user_id=user_id, parse=False)
        return resp.status == 200

    def backup_get(self, user_id, backup_id):
        return self.request("GET", f"backups/{backup_id}", user_id=user_id)

    def backup_list(self, user_id, limit: int = 10, skip: int = None, interval: bool = None):
        params = {"limit": str(limit)}
        if skip is not None:
            params["skip"] = str(skip)

        if interval is not None:
            params["interval"] = "1" if interval else "0"

        return self.request("GET", f"backups", user_id=user_id, params=params)

    def backup_interval_get(self, user_id, guild_id):
        return self.request("GET", f"guilds/{guild_id}/backups/interval", user_id=user_id)

    def backup_interval_disable(self, user_id, guild_id):
        return self.request("DELETE", f"guilds/{guild_id}/backups/interval", user_id=user_id)

    def backup_interval_enable(self, user_id, guild_id, **kwargs):
        return self.request("PUT", f"guilds/{guild_id}/backups/interval", user_id=user_id, json=kwargs)
