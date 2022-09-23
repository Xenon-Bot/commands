import base64
import binascii
import hashlib
import json
from datetime import datetime

import brotli
import ecies
import grpc
import pymongo
from dbots import *
from dbots.cmd import *
from grpc.aio import AioRpcError
from xenon.chatlogs import chatlog_pb2

from util import PremiumLevel
from .audit_logs import AuditLogType

MAX_MESSAGE_COUNT = {
    PremiumLevel.NONE: 0,
    PremiumLevel.ONE: 250,
    PremiumLevel.TWO: 500,
    PremiumLevel.THREE: 1000
}

MAX_CHATLOGS = {
    PremiumLevel.NONE: 0,
    PremiumLevel.ONE: 25,
    PremiumLevel.TWO: 50,
    PremiumLevel.THREE: 100
}


def convert_v1_to_v2(data):
    messages = []
    users = {}
    for message in data:
        users[message["author"]["id"]] = chatlog_pb2.ChatlogData.User(
            username=message["author"]["username"],
            discriminator=message["author"]["discriminator"],
            avatar=message["author"]["avatar"]
        )

        messages.append(chatlog_pb2.ChatlogData.Message(
            id=message["id"],
            content=message["content"],
            pinned=message["pinned"],
            author_id=message["author"]["id"],
            attachments=[
                chatlog_pb2.ChatlogData.Message.Attachment(
                    filename=attachment["filename"],
                    url=attachment["url"]
                )
                for attachment in message.get("attachments", [])
            ],
            embeds=[
                json.dumps(embed).encode("utf-8")
                for embed in message.get("embeds", [])
            ]
        ))

    return chatlog_pb2.ChatlogData(messages=messages, users=users)


class ChatlogModule(Module):
    async def post_setup(self):
        await self.bot.db.premium.chatlogs.create_index([("creator", pymongo.ASCENDING)])
        await self.bot.db.premium.chatlogs.create_index([("timestamp", pymongo.ASCENDING)])

    @Module.command(default_member_permissions=Permissions.FlagList.administrator)
    async def chatlog(self, ctx):
        """
        Create, load and manage your channel chatlogs
        """

    @chatlog.sub_command(extends=dict(
        message_count="The count of messages to save",
        before="The id of a message or chatlog"
    ))
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("view_channel", "read_message_history")
    @checks.cooldown(2, 30, bucket=checks.CooldownType.CHANNEL, manual=True)
    async def create(self, ctx, message_count: int = 1000, before=None):
        """
        Create a chatlog of this channel

        Get more help on the [wiki](https://wiki.xenon.bot/chatlog#creating-a-chatlog).
        """
        max_chatlogs = MAX_CHATLOGS[ctx.premium_level]
        max_message_count = MAX_MESSAGE_COUNT[ctx.premium_level]
        message_count = max(0, min(message_count, max_message_count))

        chatlog_count = await ctx.bot.db.premium.chatlogs.count_documents({"creator": ctx.author.id})
        if chatlog_count > max_chatlogs:
            await ctx.respond(**create_message(
                f"You have **exceeded the maximum count** of chatlogs. (`{chatlog_count}/{max_chatlogs}`)\n"
                f"You need to **delete old chatlogs** with `/chatlog delete` or **buy "
                f"[Xenon Premium](https://www.patreon.com/merlinfuchs)** to create new chatlogs.\n\n"
                f"*Type `/chatlog list` to view your chatlogs.*",
                f=Format.ERROR
            ), ephemeral=True)
            return

        if before is not None and not before.isdigit():
            props, data = await self._retrieve_chatlog(ctx.author.id, before)
            if data is None:
                await ctx.respond(**create_message(
                    f"The `before` argument must be a message id or a valid chatlog id.",
                    f=Format.ERROR
                ), ephemeral=True)
                return

            before = data.messages[-1].id

        await ctx.count_cooldown()
        await ctx.respond(**create_message(
            "Creating chatlog ...",
            f=Format.PLEASE_WAIT
        ), ephemeral=True)

        reply = await self.bot.rpc.chatlogs.Create(chatlog_pb2.CreateRequest(
            channel_id=ctx.channel_id,
            message_count=message_count,
            before_id=before
        ))

        chatlog_id = await self._store_chatlog(ctx.author.id, ctx.channel_id, reply.data)

        await ctx.edit_response(**create_message(
            f"Successfully **created chatlog** with the id `{chatlog_id}`.\n\n"
            f"**Usage**\n"
            f"```/chatlog info chatlog_id: {chatlog_id}```"
            f"```/chatlog load chatlog_id: {chatlog_id}```",
            f=Format.SUCCESS
        ))

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.CHATLOG_CREATE,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {"channel": ctx.channel_id}
        })

    @chatlog.sub_command()
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("manage_webhooks")
    @checks.not_in_maintenance
    @checks.cooldown(1, 30, bucket=checks.CooldownType.CHANNEL, manual=True)
    async def load(self, ctx, chatlog_id, message_count: int = 1000):
        """
        Load a previously created chatlog in this channel
        """
        max_message_count = MAX_MESSAGE_COUNT[ctx.premium_level]
        message_count = max(0, min(message_count, max_message_count))

        props, data = await self._retrieve_chatlog(ctx.author.id, chatlog_id)
        if data is None:
            await ctx.respond(**create_message(
                f"You have **no chatlog** with the id `{chatlog_id}`.\n\n"
                f"*Keep in mind that you can only access your own chatlogs.*",
                f=Format.ERROR
            ), ephemeral=True)
            return

        redis_key = f"chatlog_load:{unique_id()}"
        await ctx.bot.redis.setex(redis_key, 60 * 5, json.dumps({
            "chatlog_id": chatlog_id,
            "message_count": message_count
        }))

        # Require a confirmation by the user
        await ctx.respond(**create_message(
            "**Hey, be careful!** Are you sure that you want to load this chatlog?",
            f=Format.WARNING
        ), components=[ActionRow(
            Button(label="Confirm", style=ButtonStyle.SUCCESS, custom_id="chatlog_load_confirm", args=[redis_key]),
            Button(label="Cancel", style=ButtonStyle.DANGER, custom_id="chatlog_load_cancel")
        )], ephemeral=True)

    @Module.component(name="chatlog_load_cancel")
    async def load_cancel(self, ctx):
        await ctx.update(**create_message(
            "The loading process has been **cancelled**.\n\n"
            "Use `/chatlog load` to try again.",
            f=Format.INFO
        ), ephemeral=True)

    @Module.component(name="chatlog_load_confirm")
    async def load_confirm(self, ctx, redis_key):
        scope = await ctx.bot.redis.get(redis_key)
        if scope is None:
            await ctx.update(**create_message(
                "You were too slow, try again with `/chatlog load`",
                f=Format.ERROR
            ))
            return

        scope = json.loads(scope)
        chatlog_id, message_count = scope["chatlog_id"], scope["message_count"]

        props, data = await self._retrieve_chatlog(ctx.author.id, chatlog_id)
        if data is None:
            await ctx.update(**create_message(
                f"Something went wrong, try again with `/chatlog load`",
                f=Format.ERROR
            ), ephemeral=True)
            return

        await self.load.cooldown.count(ctx)

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.CHATLOG_LOAD,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {"channel": ctx.channel_id}
        })

        await ctx.update(**create_message(
            "**The chatlog will start loading now**. Please be patient, this can take a while!\n\n"
            "*This message might not be updated.*",
            f=Format.INFO
        ))

        guild = await ctx.fetch_guild()
        if guild.premium_tier == PremiumTier.TIER_2:
            max_file_size = 50e6
        elif guild.premium_tier == PremiumTier.TIER_3:
            max_file_size = 100e6
        else:
            max_file_size = 8e6

        try:
            await self.bot.rpc.chatlogs.Load(chatlog_pb2.LoadRequest(
                channel_id=ctx.channel_id,
                message_count=message_count,
                max_file_size=int(max_file_size),
                data=data
            ))
        except AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                await ctx.update(**create_message(
                    f"Xenon doesn't seem to be on this server, "
                    f"please click [here](https://xenon.bot/invite) to invite it again.",
                    f=Format.ERROR
                ))
                return
            elif e.code() == grpc.StatusCode.CANCELLED:
                return
            else:
                raise

        try:
            await ctx.update(**create_message(
                f"Successfully **loaded the chatlog**.",
                f=Format.SUCCESS
            ))
        except rest.HTTPException:
            pass

    @chatlog.sub_command()
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def info(self, ctx, chatlog_id):
        """
        Get information about a previously created chatlog
        """
        props, data = await self._retrieve_chatlog(ctx.author.id, chatlog_id)
        if data is None:
            await ctx.respond(**create_message(
                f"You have **no chatlog** with the id `{chatlog_id}`.\n\n"
                f"*Keep in mind that you can only access your own chatlogs.*",
                f=Format.ERROR
            ), ephemeral=True)
            return

        first_mesasge_id = "-"
        last_message_id = "-"
        if len(data.messages) != 0:
            first_message_id = data.messages[-1].id
            last_message_id = data.messages[0].id

        await ctx.respond(embeds=[{
            "description": f"**Chatlog Info - <#{props['channel']}>**",
            "color": Format.INFO.color,
            "fields": [
                {
                    "name": "Created At",
                    "value": datetime_to_string(props["timestamp"]),
                    "inline": False
                },
                {
                    "name": "Message Count",
                    "value": len(data.messages),
                    "inline": False
                },
                {
                    "name": "First Message",
                    "value": f"`{first_mesasge_id}`",
                    "inline": True
                },
                {
                    "name": "Last Message",
                    "value": f"`{last_message_id}`",
                    "inline": True
                },
            ]
        }], ephemeral=True)

    @chatlog.sub_command(extends=dict(
        page="The page to display (default 1)"
    ))
    @checks.cooldown(2, 10, bucket=checks.CooldownType.AUTHOR)
    async def list(self, ctx, page: int = 1, master_key: str = None):
        """
        Get a list of all your previously created chatlogs
        """
        page = max(page, 1)
        _filter = {"creator": ctx.author.id}
        total_count = await self.bot.db.premium.chatlogs.count_documents(_filter)
        if total_count == 0:
            await ctx.respond(**create_message(
                "You **don't have any chatlogs** yet. Use `/chatlog create` to create one.",
                f=Format.INFO
            ), ephemeral=True)
            return

        fields = []
        async for chatlog in self.bot.db.premium.chatlogs.find(
                _filter,
                sort=[("timestamp", pymongo.DESCENDING)],
                limit=10,
                skip=(page - 1) * 10,
                projection=("_id", "timestamp", "data.key", "channel")
        ):
            properties = []

            chatlog_id = chatlog['_id'].upper()

            fields.append(dict(
                name=chatlog_id + f" • {' '.join(properties)}" * (len(properties) > 0),
                value=f"<#{chatlog['channel']}> (`{datetime_to_string(chatlog['timestamp'])} UTC`)"
            ))

        description = f"Displaying **{(page - 1) * 10 + 1}** - **{min(page * 10, total_count)}** " \
                      f"of **{total_count}** total chatlogs"
        if total_count > page * 10:
            description += f"\n\nType `/chatlog list page: {page + 1}` for the next page"

        await ctx.respond(embeds=[dict(
            title="Chatlog List",
            fields=fields,
            color=Format.INFO.color,
            description=f"{description}\n​"
        )], ephemeral=True)

    @chatlog.sub_command()
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def delete(self, ctx, chatlog_id):
        """
        Delete one of your previously created chatlogs
        """
        result = await ctx.bot.db.premium.chatlogs.delete_one({"_id": chatlog_id.lower(), "creator": ctx.author.id})
        if result.deleted_count == 0:
            await ctx.respond(**create_message(
                f"You have **no chatlog** with the id `{chatlog_id}`.",
                f=Format.ERROR
            ), ephemeral=True)
        else:
            await ctx.respond(**create_message(
                f"Successfully **deleted the chatlog**.",
                f=Format.SUCCESS
            ), ephemeral=True)

    @chatlog.sub_command(extends=dict(
        older_than=dict(
            description="Only chatlogs that are older than this will be deleted",
            choices=(
                    ("24 hours", "24h"),
                    ("2 days", "2d"),
                    ("3 days", "3d"),
                    ("7 days", "7d"),
                    ("14 days", "14d"),
                    ("30 days", "30d")
            )
        ),
    ))
    @checks.cooldown(1, 30, bucket=checks.CooldownType.AUTHOR, manual=True)
    async def purge(self, ctx, older_than=""):
        """
        Delete all your previously created chatlogs
        """
        td = string_to_timedelta(older_than)
        _filter = {
            "creator": ctx.author.id,
            "timestamp": {"$lte": datetime.utcnow() - td}
        }

        total_count = await self.bot.db.premium.chatlogs.count_documents({"creator": ctx.author.id})
        delete_count = await self.bot.db.premium.chatlogs.count_documents(_filter)

        if delete_count == 0:
            await ctx.respond(**create_message(
                "There are **no chatlogs** to delete.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        redis_key = f"chatlog_purge:{unique_id()}"
        await ctx.bot.redis.setex(redis_key, 60 * 5, json.dumps({
            "older_than": older_than,
        }))

        await ctx.respond(**create_message(
            f"Are you sure that you want to delete **{delete_count}** of **{total_count}** total chatlogs?",
            f=Format.WARNING
        ), components=[ActionRow(
            Button(label="Confirm", style=ButtonStyle.SUCCESS, custom_id="chatlog_purge_confirm", args=[redis_key]),
            Button(label="Cancel", style=ButtonStyle.DANGER, custom_id="chatlog_purge_cancel")
        )], ephemeral=True)

    @Module.component(name="chatlog_purge_cancel")
    async def purge_cancel(self, ctx):
        await ctx.update(**create_message(
            "Your chatlogs have **not** been **deleted**.\n\n"
            "Use `/chatlog purge` to try again.",
            f=Format.INFO
        ), ephemeral=True)

    @Module.component(name="chatlog_purge_confirm")
    async def purge_confirm(self, ctx, redis_key):
        scope = await ctx.bot.redis.get(redis_key)
        if scope is None:
            await ctx.update(**create_message(
                "You were too slow, try again with `/chatlog purge`",
                f=Format.ERROR
            ))
            return

        scope = json.loads(scope)
        older_than = scope["older_than"]

        td = string_to_timedelta(older_than)
        _filter = {
            "creator": ctx.author.id,
            "timestamp": {"$lte": datetime.utcnow() - td}
        }

        await self.purge.cooldown.count(ctx)

        total_count = await self.bot.db.premium.chatlogs.count_documents({"creator": ctx.author.id})
        result = await ctx.bot.db.premium.chatlogs.delete_many(_filter)
        await ctx.update(**create_message(
            f"Successfully deleted **{result.deleted_count}** of **{total_count}** total chatlogs.",
            f=Format.SUCCESS
        ))

    async def _store_chatlog(self, creator, channel, data):
        raw = await self.bot.loop.run_in_executor(None, lambda: brotli.compress(data.SerializeToString()))
        chatlog_id = unique_id().upper()

        doc = {
            "_id": chatlog_id.lower(),
            "version": 2,
            "creator": creator,
            "timestamp": datetime.utcnow(),
            "channel": channel,
            "data": {
                "id": channel,
                "raw": raw
            }
        }

        await self.bot.db.premium.chatlogs.insert_one(doc)
        return chatlog_id

    async def _retrieve_chatlog(self, creator, chatlog_id):
        doc = await self.bot.db.premium.chatlogs.find_one({"_id": chatlog_id.lower(), "creator": creator})
        if doc is None:
            return None, None

        data = chatlog_pb2.ChatlogData()
        await self.bot.loop.run_in_executor(None, lambda: data.ParseFromString(brotli.decompress(doc["data"]["raw"])))
        del doc["data"]
        return doc, data

    async def _delete_chatlog(self, creator, chatlog_id):
        result = await self.bot.db.premium.chatlogs.delete_one({
            "_id": chatlog_id,
            "creator": creator
        })
        return result.deleted_count > 0

    async def _delete_chatlogs(self, _filter):
        result = await self.bot.db.premium.chatlogs.delete_many(_filter)
        return result.deleted_count
