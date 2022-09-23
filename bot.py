from dbots import *
from dbots.cmd import *
from motor.motor_asyncio import AsyncIOMotorClient
import json
from os import environ as env
import asyncio
import traceback
import sys
from datetime import datetime
import grpc.aio
from xenon.backups import backup_pb2_grpc
from xenon.chatlogs import chatlog_pb2_grpc

from util import *


class RpcCollection:
    def __init__(self, host):
        channel = grpc.aio.insecure_channel(host)

        self.chatlogs = chatlog_pb2_grpc.ChatlogServiceStub(channel)
        self.backups = backup_pb2_grpc.BackupServiceStub(channel)


class Xenon(InteractionBot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mongo = None
        self._invite = None
        self._support_invite = None

        self.rpc = None

        self.component(self._delete_button, name="delete")

    @property
    def db(self):
        return self.mongo.xenon

    async def _delete_button(self, ctx):
        ctx.defer()
        await ctx.delete_response()

    async def on_command_error(self, ctx, e):
        if isinstance(e, asyncio.CancelledError):
            raise e

        else:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            print("Command Error:\n", tb, file=sys.stderr)

            error_id = unique_id()
            name = None
            args = None
            if isinstance(ctx, CommandContext):
                name = ctx.command.full_name
                args = {arg.name: arg.value for arg in ctx.args}
            elif isinstance(ctx, ComponentContext):
                name = ctx.component.name
            elif isinstance(ctx, ModalContext):
                name = ctx.modal.name

            await self.redis.setex(f"cmd:errors:{error_id}", 60 * 60 * 24, json.dumps({
                "command": name,
                "args": args,
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
        premium_level = 0
        user_doc = await self.db.users.find_one({"_id": payload.author.id})
        if user_doc is not None:
            premium_level = user_doc.get("tier", 0)

        payload.premium_level = PremiumLevel(premium_level)
        return await super().execute_component(component, payload, args)

    async def execute_command(self, command, payload, remaining_options):
        await self.redis.hincrby("cmd:commands", command.full_name, 1)

        blacklist = await self.db.blacklist.find_one({"_id": payload.author.id})
        if blacklist is None and payload.guild_id:
            blacklist = await self.db.blacklist.find_one({"_id": payload.guild_id})

        if blacklist is not None and command.full_name not in {"opt out", "opt in"}:
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

        premium_level = 0
        user_doc = await self.db.users.find_one({"_id": payload.author.id})
        if user_doc is not None:
            premium_level = user_doc.get("tier", 0)

        premium_level = 3

        payload.premium_level = PremiumLevel(premium_level)

        allowed_commands = {
            "settings show", "settings permissions", "settings reset", "leave", "ping", "support", "audit logs", "help",
            "opt in", "opt out"
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
        return "https://discord.com/api/oauth2/authorize" \
               "?client_id=524652984425250847&permissions=8&scope=applications.commands%20bot"

        if self._invite:
            return self._invite

        invite = "https://xenon.bot/premium/invite"
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

    async def setup(self, redis_url="redis://localhost"):
        self.rpc = RpcCollection(env.get("BACKUPS_SERVICE", "127.0.0.1:8081"))
        self.mongo = AsyncIOMotorClient(env.get("MONGO_URL", "mongodb://localhost"))
        await super().setup(redis_url)
