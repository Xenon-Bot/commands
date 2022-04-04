import asyncio
import orjson
from urllib.parse import quote as urlquote
import aiohttp
from enum import Enum
from os import environ as env

from .entities import *
from .flags import *
from .errors import *

__all__ = (
    "Route",
    "HTTPClient",
    "File",
)


async def json_or_text(response):
    text = await response.text(encoding='utf-8')
    try:
        if response.headers['content-type'] == 'application/json':
            return orjson.loads(text)
    except KeyError:
        pass

    return text


def entity_or_id(thing):
    if isinstance(thing, Entity):
        return thing.id

    return thing


def make_json(options, allowed=None, converters=None):
    json = options.pop("raw", {})
    json.update(options)

    def _default_converter(v):
        if isinstance(v, Enum) or isinstance(v, Flags):
            return v.value

        if isinstance(v, Entity):
            return v.id

        return v

    converters = converters or {}
    for k, v in json.items():
        converter = converters.get(k, _default_converter)
        json[k] = converter(v)

    if allowed is None:
        return json

    else:
        return {k: v for k, v in json.items() if k in allowed}


class File:
    __slots__ = ("fp", "filename", "_original_pos", "_closer")

    def __init__(self, fp, filename=None, *, spoiler=False):
        self.fp = fp
        self.filename = filename or getattr(fp, 'name', None)
        if spoiler:
            self.filename = f"SPOILER_{self.filename}"

        # aiohttp closes file objects automatically, we don't want that
        self._closer = self.fp.close
        self.fp.close = lambda: None

    def reset(self):
        self.fp.seek(0)

    def close(self):
        self.fp.close = self._closer
        self._closer()


class Route:
    BASE = f"{env.get('DISCORD_API_URL', 'https://discord.com')}/api/v9"

    def __init__(self, method, path, **params):
        self.method = method
        self.path = path.strip("/")

        self.url = f"{self.BASE}/{self.path}".format(**{k: urlquote(str(v)) for k, v in params.items()})

        self._channel_id = params.get("channel_id")
        self._guild_id = params.get("guild_id")
        self._webhook_id = params.get("webhook_id")

    @property
    def bucket(self):
        if self._webhook_id is not None:
            return self._webhook_id

        else:
            return '{0._channel_id}:{0._guild_id}:{0.path}'.format(self)


class RouteMixin:
    application_id: str

    async def request(self, *args, **kwargs):
        # Must be overwritten by the deriving client
        pass

    def get_global_commands(self):
        return self.request(
            Route("GET", "/applications/{application_id}/commands", application_id=self.application_id)
        )

    def get_guild_commands(self, guild):
        return self.request(
            Route("GET", "/applications/{application_id}/guilds/{guild_id}/commands",
                  application_id=self.application_id, guild_id=entity_or_id(guild))
        )

    def get_global_command(self, command):
        return self.request(
            Route("GET", "/applications/{application_id}/commands/{command_id}",
                  application_id=self.application_id, command_id=entity_or_id(command))
        )

    def get_guild_command(self, guild, command):
        return self.request(
            Route("GET", "/applications/{application_id}/guilds/{guild_id}/commands/{command_id}",
                  application_id=self.application_id, guild_id=entity_or_id(guild),
                  command_id=entity_or_id(command))
        )

    def create_global_command(self, data):
        return self.request(
            Route("POST", "/applications/{application_id}/commands",
                  application_id=self.application_id),
            json=data
        )

    def create_guild_command(self, guild, data):
        return self.request(
            Route("POST", "/applications/{application_id}/guilds/{guild_id}/commands",
                  application_id=self.application_id, guild_id=entity_or_id(guild)),
            json=data
        )

    def edit_global_command(self, command, data):
        return self.request(
            Route("PATCH", "/applications/{application_id}/commands/{command_id}",
                  application_id=self.application_id, command_id=entity_or_id(command)),
            json=data
        )

    def edit_guild_command(self, guild, command, data):
        return self.request(
            Route("PATCH", "/applications/{application_id}/guilds/{guild_id}/commands/{command_id}",
                  application_id=self.application_id, guild_id=entity_or_id(guild), command_id=entity_or_id(command)),
            json=data
        )

    def delete_global_command(self, command):
        return self.request(
            Route("DELETE", "/applications/{application_id}/commands/{command_id}",
                  application_id=self.application_id, command_id=entity_or_id(command))
        )

    def delete_guild_command(self, guild, command):
        return self.request(
            Route("DELETE", "/applications/{application_id}/guilds/{guild_id}/commands/{command_id}",
                  application_id=self.application_id, guild_id=entity_or_id(guild), command_id=entity_or_id(command))
        )

    def replace_global_commands(self, data):
        return self.request(
            Route("PUT", "/applications/{application_id}/commands", application_id=self.application_id),
            json=data
        )

    def replace_guild_commands(self, guild, data):
        return self.request(
            Route("PUT", "/applications/{application_id}/guilds/{guild_id}/commands",
                  application_id=self.application_id, guild_id=entity_or_id(guild)),
            json=data
        )

    def create_interaction_response(self, interaction_token, files=None, **options):
        return self.request(
            Route("POST", "/webhooks/{application_id}/{webhook_token}",
                  application_id=self.application_id, webhook_token=interaction_token),
            files=files,
            json=make_json(options),
            converter=Message
        )

    def edit_interaction_response(self, interaction_token, message="@original", files=None, **options):
        return self.request(
            Route("PATCH", "/webhooks/{application_id}/{webhook_token}/messages/{message_id}",
                  application_id=self.application_id, webhook_token=interaction_token,
                  message_id=entity_or_id(message)),
            files=files,
            json=make_json(options),
            converter=Message
        )

    def delete_interaction_response(self, interaction_token, message="@original"):
        return self.request(
            Route("DELETE", "/webhooks/{application_id}/{webhook_token}/messages/{message_id}",
                  application_id=self.application_id, webhook_token=interaction_token,
                  message_id=entity_or_id(message))
        )

    def get_interaction_response(self, interaction_token, message="@original"):
        # We currently have to use PATCH because discord didn't add a GET endpoint yet
        return self.request(
            Route("PATCH", "/webhooks/{application_id}/{webhook_token}/messages/{message_id}",
                  application_id=self.application_id, webhook_token=interaction_token,
                  message_id=entity_or_id(message)),
            json={},
            converter=Message
        )

    def set_command_guild_permissions(self, guild, command, permissions):
        return self.request(
            Route("PUT", "/applications/{application_id}/guilds/{guild_id}/commands/{command_id}/permissions",
                  application_id=self.application_id, guild_id=entity_or_id(guild), command_id=entity_or_id(command)),
            json={"permissions": permissions}
        )

    def get_command_guild_permissions(self, guild, command):
        return self.request(
            Route("GET", "/applications/{application_id}/guilds/{guild_id}/commands/{command_id}/permissions",
                  application_id=self.application_id, guild_id=entity_or_id(guild), command_id=entity_or_id(command))
        )


class HTTPClient(RouteMixin):
    def __init__(self, token, application_id, session, **kwargs):
        self._token = token
        self.application_id = application_id
        self._session = session

        self.max_retries = kwargs.get("max_retries", 5)

    async def close(self):
        if self._session is not None:
            await self._session.close()

    async def _perform_request(self, route, **kwargs):
        headers = {
            "User-Agent": "",
            "Authorization": kwargs.pop("auth", f"Bot {self._token}")
        }

        if "json" in kwargs:
            data = kwargs.pop("json")
            if data is not None:
                headers["Content-Type"] = "application/json"
                kwargs["data"] = orjson.dumps(data)

        if "reason" in kwargs:
            headers["X-Audit-Log-Reason"] = urlquote(kwargs.pop("reason") or "", safe="/ ")

        async with self._session.request(
                method=route.method,
                url=route.url,
                headers=headers,
                raise_for_status=False,
                **kwargs
        ) as resp:
            data = await json_or_text(resp)
            if 300 > resp.status >= 200:
                return data

            raise HTTPException(resp.status, data)

    async def request(self, route, converter=None, wait=True, files=None, **kwargs):
        for i in range(self.max_retries):
            options = kwargs.copy()

            try:
                if files is not None:
                    for file in files:
                        file.reset()

                    data = options.get("data", aiohttp.FormData())
                    if "json" in options:
                        data.add_field("payload_json", orjson.dumps(options.pop("json")).decode("utf-8"))

                    for i, file in enumerate(files):
                        data.add_field(f"file{i}", file.fp, filename=file.filename,
                                       content_type='application/octet-stream')

                    options["data"] = data

                result = await self._perform_request(route, **options)
                if converter:
                    return converter(result)

                return result
            except HTTPException as e:
                if e.status == 400:
                    raise HTTPBadRequest(e.text)

                elif e.status == 401:
                    raise HTTPUnauthorized(e.text)

                elif e.status == 403:
                    raise HTTPForbidden(e.text)

                elif e.status == 404:
                    raise HTTPNotFound(e.text)

                elif e.status == 429:
                    raise HTTPTooManyRequests(e.text)

                elif e.status < 500 or i == self.max_retries - 1:
                    raise e

                else:
                    await asyncio.sleep(i)
