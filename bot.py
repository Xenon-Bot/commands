from dbots import *
from dbots.cmd import *
from motor.motor_asyncio import AsyncIOMotorClient
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
import functools

from util import *


class RpcCollection:
    def __init__(self, host):
        channel = grpclib.client.Channel(*host.split(":"))
        self.backups = backups_grpc.BackupsStub(channel)
        self.chatlogs = chatlogs_grpc.ChatlogsStub(channel)


class Xenon(InteractionBot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mongo = AsyncIOMotorClient(env.get("MONGO_URL", "mongodb://localhost"))
        self.db = self.mongo.xenon
        self._invite = None
        self._support_invite = None

        self.rpc = RpcCollection(env.get("BACKUPS_SERVICE", "127.0.0.1:8081"))

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
                    if isinstance(ctx, CommandContext):
                        scope.set_tag("command", ctx.command.full_name)
                        scope.set_tag("args", ", ".join([f"{arg.name}: {arg.value}" for arg in ctx.args]))

                    scope.set_tag("guild_id", ctx.guild_id)
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
                    f"[Support Server](<{await ctx.bot.get_support_invite()}>).\n\n"
                    f"**Error Code**: `{error_id.upper()}`",
                    f=Format.ERROR
                ), ephemeral=True)
            except rest.HTTPException:
                pass

    async def execute_component(self, component, payload, args):
        raw_premium_level = await self.redis.hget("premium:users", payload.author.id) or "0"
        payload.premium_level = PremiumLevel(int(raw_premium_level))
        return await super().execute_component(component, payload, args)

    async def execute_command(self, command, payload, remaining_options):
        await self.redis.hincrby("cmd:commands", command.full_name, 1)

        blacklist = await self.db.blacklist.find_one({"_id": payload.author.id})
        if blacklist is None and payload.guild_id:
            blacklist = await self.db.blacklist.find_one({"_id": payload.guild_id})

        if blacklist is not None:
            if blacklist.get("guild"):
                return InteractionResponse.message(**create_message(
                    "This server is **no longer allowed to use this bot** for the following reason:"
                    f"```{blacklist['reason']}```",
                    f=Format.ERROR
                ), ephemeral=True)
            else:
                return InteractionResponse.message(**create_message(
                    "You are **no longer allowed to use this bot** for the following reason:"
                    f"```{blacklist['reason']}```",
                    f=Format.ERROR
                ), ephemeral=True)


        raw_premium_level = await self.redis.hget("premium:users", payload.author.id) or "0"
        payload.premium_level = PremiumLevel(int(raw_premium_level))

        allowed_commands = {
            "settings show", "settings permissions", "settings reset", "leave", "ping", "support", "audit logs", "help"
        }
        if payload.premium_level == PremiumLevel.NONE and command.full_name not in allowed_commands:
            return InteractionResponse.message(
                content="You **need** to buy **Xenon Premium** to be able to use this bot and its commands.\n\n"
                        "You can **buy Premium [here](<https://patreon.com/merlinfuchs>)** and "
                        "get a full list of features [here](<https://wiki.xenon.bot/premium>).\n\n\n"
                        "*If you have already bought Xenon Premium please click "
                        "[here](<https://wiki.xenon.bot/premium#redeem-perks>)*.",
                ephemeral=True
            )

        return await super().execute_command(command, payload, remaining_options)

    async def get_invite(self):
        if self._invite:
            return self._invite

        invite = "https://xenon.bot/invite"
        while "discord.com" not in invite:
            async with self.session.get(invite, allow_redirects=False) as resp:
                if 400 > resp.status >= 300:
                    invite = resp.headers["Location"]
                else:
                    break

        self._invite = invite
        return invite

    async def get_support_invite(self):
        if self._support_invite:
            return self._support_invite

        invite = "https://xenon.bot/discord"
        while "discord.com" not in invite:
            async with self.session.get(invite, allow_redirects=False) as resp:
                if 400 > resp.status >= 300:
                    invite = resp.headers["Location"]
                else:
                    break

        self._support_invite = invite
        return invite
