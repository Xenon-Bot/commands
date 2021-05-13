from dbots.cmd import *
from dbots import *
import base64
import binascii
import pymongo
import ecies
from datetime import datetime
import asyncio
from dbots.protos import chatlogs_pb2
import brotli
import hashlib

from util import PremiumLevel
from . import encryption
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
        users[message["author"]["id"]] = chatlogs_pb2.ChatlogData.User(
            username=message["author"]["username"],
            discriminator=message["author"]["discriminator"],
            avatar=message["author"]["avatar"]
        )

        messages.append(chatlogs_pb2.ChatlogData.Message(
            id=message["id"],
            content=message["content"],
            pinned=message["pinned"],
            attachments=[
                chatlogs_pb2.ChatlogData.Message.Attachment(
                    filename=attachment["filename"],
                    url=attachment["url"]
                )
                for attachment in message["attachments"]
            ],
            embed=[]  # TODO: Convert embeds
        ))

    return chatlogs_pb2.ChatlogData(messages=messages, users=users)


class ChatlogModule(Module):
    @Module.command()
    async def chatlog(self, ctx):
        """
        Create, load and manage your channel chatlogs
        """

    @chatlog.sub_command(extends=dict(
        message_count="The count of messages to save",
        before="The id of the message"
    ))
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("view_channel", "read_message_history")
    async def create(self, ctx, message_count: int = 1000, before=None):
        """
        Create a chatlog of this channel

        Get more help on the [wiki](https://wiki.xenon.bot/chatlog#creating-a-chatlog).
        """
        max_chatlogs = MAX_CHATLOGS[ctx.premium_level]
        max_message_count = MAX_MESSAGE_COUNT[ctx.premium_level]
        message_count = min(message_count, max_message_count)

        chatlog_count = await ctx.bot.db.premium.chatlogs.count_documents({"creator": ctx.author.id})
        if chatlog_count > max_chatlogs:
            await ctx.respond(**create_message(
                f"You have **exceeded the maximum count** of backups. (`{chatlog_count}/{max_chatlogs}`)\n"
                f"You need to **delete old backups** with `/backup delete` or **buy "
                f"[Xenon Premium](https://www.patreon.com/merlinfuchs)** to create new backups.\n\n"
                f"*Type `/backup list` to view your backups.*",
                f=Format.ERROR
            ))
            return

        # await ctx.count_cooldown()
        await ctx.respond(**create_message("Creating chatlog ...", f=Format.PLEASE_WAIT))

        reply = await self.bot.rpc.chatlogs.Create(chatlogs_pb2.CreateRequest(
            channel_id=ctx.channel_id,
            message_count=message_count,
            before_id=before
        ))

        chatlog_id = await self._store_chatlog(ctx.author.id, ctx.channel_id, reply.data)

        await ctx.edit_response(**create_message(
            f"Successfully **created chatlog** with the id `{chatlog_id}`.\n\n"
            f"**Usage**\n"
            f"```/backup info backup_id: {chatlog_id}```"
            f"```/backup load backup_id: {chatlog_id}```",
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
    async def load(self, ctx, chatlog_id, message_count: int = 1000):
        """
        Load a previously created chatlog in this channel
        """

    @chatlog.sub_command()
    async def info(self, ctx, chatlog_id):
        """
        Get information about a previously created chatlog
        """

    @chatlog.sub_command(extends=dict(
        page="The page to display (default 1)",
        master_kay="The master key (only for encrypted backups)"
    ))
    @checks.cooldown(2, 10, bucket=checks.CooldownType.AUTHOR)
    async def list(self, ctx, page: int = 1, master_key: str = None):
        """
        Get a list of all your previously created chatlogs
        """
        _filter = {"creator": ctx.author.id}
        total_count = await self.bot.db.premium.chatlogs.count_documents(_filter)
        if total_count == 0:
            await ctx.respond(**create_message(
                "You **don't have any chatlogs** yet. Use `/chatlog create` to create one.",
                f=Format.INFO
            ))
            return

        if master_key is not None:
            try:
                master_key = base64.b32decode(master_key + "====")
            except binascii.Error:
                master_key = None

        fields = []
        contains_encrypted = False
        async for chatlog in self.bot.db.premium.chatlogs.find(
                _filter,
                sort=[("timestamp", pymongo.DESCENDING)],
                limit=10,
                skip=(page - 1) * 10,
                projection=("_id", "timestamp", "encrypted", "data.key", "data.name")
        ):
            properties = []
            if chatlog.get("encrypted"):
                properties.append("🔒")

            chatlog_id = chatlog['_id'].upper()
            if chatlog.get("encrypted"):
                chatlog_id = "encrypted"
                if master_key is not None:
                    try:
                        chatlog_id = encryption.key_to_id(ecies.decrypt(master_key, chatlog["data"]["key"]))
                    except (binascii.Error, ValueError):
                        contains_encrypted = True
                else:
                    contains_encrypted = True

            fields.append(dict(
                name=chatlog_id + f" • {' '.join(properties)}" * (len(properties) > 0),
                value=f"#{chatlog['data']['name']} (`{datetime_to_string(chatlog['timestamp'])} UTC`)"
            ))

        description = f"Displaying **{(page - 1) * 10 + 1}** - **{min(page * 10, total_count)}** " \
                      f"of **{total_count}** total chatlogs"
        if contains_encrypted:
            description += f"\n\n*Some chatlogs are encrypted, supply the master key to see the chatlog ids.*"
        if total_count > page * 10:
            description += f"\n\nType `/chatlog list page: {page + 1}` for the next page"

        await ctx.respond(embeds=[dict(
            title="Chatlog List",
            fields=fields,
            color=Format.INFO.color,
            description=f"{description}\n​"
        )])

    @chatlog.sub_command()
    async def delete(self, ctx, chatlog_id):
        """
        Delete one of your previously created chatlogs
        """
        result = await ctx.bot.db.premium.chatlogs.delete_one({"_id": chatlog_id.lower(), "creator": ctx.author.id})
        if result.deleted_count == 0:
            await ctx.respond(**create_message(
                f"You have **no chatlog** with the id `{chatlog_id}`.",
                f=Format.ERROR
            ))
        else:
            await ctx.respond(**create_message(
                f"Successfully **deleted the chatlog**.",
                f=Format.SUCCESS
            ))

    @chatlog.sub_command(extends=dict(
        older_than="Only backups that are older than this will be deleted (e.g. 24h)"
    ))
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
            ))
            return

        await ctx.respond(**create_message(
            f"Are you sure that you want to delete **{delete_count}** of **{total_count}** total chatlogs?\n\n"
            "Type `/confirm` to confirm this action and continue.",
            f=Format.WARNING
        ))

        try:
            await self.bot.wait_for_confirmation(ctx, timeout=60)
        except asyncio.TimeoutError:
            try:
                await ctx.delete_response()
            except rest.HTTPNotFound:
                pass
            return

        result = await ctx.bot.db.premium.chatlogs.delete_many(_filter)

        await ctx.count_cooldown()
        await ctx.edit_response(**create_message(
            f"Successfully deleted **{result.deleted_count}** of **{total_count}** total backups.",
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
            "encrypted": False,
            "data": {
                "id": channel,
                "raw": raw
            }
        }

        public_key = await encryption.get_public_key(self.bot, creator)
        if public_key is not None:
            key_bytes, nonce_bytes, symmetric_key = encryption.get_symmetric_key()
            chatlog_id = encryption.key_to_id(key_bytes)
            doc["_id"] = base64.b64encode(hashlib.sha3_512(key_bytes).digest()).decode()
            doc["encrypted"] = True
            doc["data"]["raw"] = await self.bot.loop.run_in_executor(None, lambda: symmetric_key.encrypt(raw))
            doc["data"]["nonce"] = nonce_bytes
            doc["data"]["key"] = ecies.encrypt(public_key, key_bytes)

        await self.bot.db.premium.chatlogs.insert_one(doc)
        return chatlog_id

    async def _retrieve_chatlog(self, creator, chatlog_id):
        if len(chatlog_id) > 20:
            try:
                key_bytes = encryption.id_to_key(chatlog_id)
            except (binascii.Error, ValueError):
                return None, None
            identifier = base64.b64encode(hashlib.sha3_512(key_bytes).digest()).decode()
            doc = await self.bot.db.premium.chatlogs.find_one({"_id": identifier, "creator": creator})
            if doc is None:
                return None, None

            _, _, key = encryption.get_symmetric_key(key_bytes, doc["data"]["nonce"])
            doc["data"]["raw"] = await self.bot.loop.run_in_executor(None, lambda: key.decrypt(doc["data"]["raw"]))

        else:
            doc = await self.bot.db.backups.find_one({"_id": chatlog_id.lower(), "creator": creator})
            if doc is None:
                return None, None

        if doc.get("version") != 2:
            data = convert_v1_to_v2(doc["data"])
            del doc["data"]
            return doc, data

        data = chatlogs_pb2.ChatlogData()
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
