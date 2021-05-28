from dbots import *
from dbots.cmd import *
from motor.motor_asyncio import AsyncIOMotorClient
import aioredis
import json
from os import environ as env
import asyncio
import traceback
import sys
from datetime import datetime
import grpclib.client
from dbots.protos import backups_grpc, chatlogs_grpc
import weakref
import sentry_sdk

from util import *


class RpcCollection:
    def __init__(self):
        channel = grpclib.client.Channel("localhost", 8081)
        self.backups = backups_grpc.BackupsStub(channel)
        self.chatlogs = chatlogs_grpc.ChatlogsStub(channel)


class Xenon(InteractionBot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mongo = AsyncIOMotorClient(env.get("MONGO_URL", "mongodb://localhost"))
        self.db = self.mongo.xenon
        self.redis = None
        self.http = None
        self.relay = None

        self.rpc = RpcCollection()

        self.component(self._delete_button, name="delete")

    async def _delete_button(self, ctx):
        ctx.defer()
        await ctx.delete_response()

    async def on_command_error(self, ctx, e):
        if isinstance(e, asyncio.CancelledError):
            raise e

        else:
            if not isinstance(e, rest.HTTPException):
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("command", ctx.command.full_name)
                    scope.set_tag("guild_id", ctx.guild_id)
                    scope.set_tag("args", ", ".join([f"{arg.name}: {arg.value}" for arg in ctx.args]))
                    scope.set_user({
                        "id": ctx.author.id,
                        "name": ctx.author.name,
                        "discriminator": ctx.author.discriminator}
                    )
                    sentry_sdk.capture_exception(e)

            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            print("Command Error:\n", tb, file=sys.stderr)

            error_id = unique_id()
            await self.redis.setex(f"cmd:errors:{error_id}", 60 * 60 * 24, json.dumps({
                "command": ctx.command.full_name,
                "args": {arg.name: arg.value for arg in ctx.args},
                "timestamp": datetime.utcnow().timestamp(),
                "author": ctx.author.id,
                "traceback": tb
            }))
            try:
                await ctx.respond(**create_message(
                    "An unexpected error occurred. Please report this on the "
                    "[Support Server](https://xenon.bot/discord).\n\n"
                    f"**Error Code**: `{error_id.upper()}`",
                    f=Format.ERROR
                ), ephemeral=True)
            except rest.HTTPException:
                pass

    async def execute_command(self, command, payload, remaining_options):
        await self.redis.hincrby("cmd:commands", command.full_name, 1)

        raw_premium_level = await self.redis.hget("premium:users", payload.author.id) or "0"
        premium_level = PremiumLevel(int(raw_premium_level))
        if premium_level == PremiumLevel.NONE:
            return InteractionResponse.message(
                content="You **need** to buy **Xenon Premium** to be able to use this bot and its commands.\n\n"
                        "You can **buy Premium [here](https://patreon.com/merlinfuchs)** and "
                        "get a full list of features [here](https://wiki.xenon.bot/premium).\n\n\n"
                        "*If you have already bought Xenon Premium please click "
                        "[here](https://wiki.xenon.bot/premium#redeem-perks)*.",
                ephemeral=True
            )
        else:
            payload.premium_level = premium_level

        return await super().execute_command(command, payload, remaining_options)
