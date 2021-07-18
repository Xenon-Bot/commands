from dbots.cmd import *
from dbots import *
import re
from enum import IntEnum
import pymongo
import asyncio
import pymongo.errors
from datetime import datetime

from .audit_logs import AuditLogType

SYNC_DIRECTIONS = [
    ("from", "from"),
    ("to", "to"),
    ("both ways", "from-to")
]


class SyncType(IntEnum):
    MESSAGES = 0
    BANS = 1
    ROLE = 2


class SyncModule(Module):
    async def post_setup(self):
        await self.bot.db.premium.syncs.create_index(
            [("type", pymongo.ASCENDING), ("target", pymongo.ASCENDING), ("source", pymongo.ASCENDING)],
            unique=True
        )
        await self.bot.db.premium.syncs.create_index([("guilds", pymongo.ASCENDING)])
        await self.bot.db.premium.syncs.create_index([("target_guild", pymongo.ASCENDING)])

    @Module.command()
    async def sync(self, ctx):
        """
        Sync events from one server or channel to another
        """

    @sync.sub_command(extends=dict(
        page="The page to display (default 1)"
    ))
    @guild_only
    @checks.has_permissions_level()
    async def list(self, ctx, page: int = 1):
        """
        List all syncs related to this server
        """
        page = max(page, 1)
        _filter = {"guilds": ctx.guild_id}
        total_count = await self.bot.db.premium.syncs.count_documents(_filter)
        if total_count == 0:
            await ctx.respond(**create_message(
                "There **aren't any syncs** attached to this server yet.",
                f=Format.INFO
            ), ephemeral=True)
            return

        fields = []
        async for sync in self.bot.db.premium.syncs.find(
                _filter,
                limit=10,
                skip=(page - 1) * 10,
                projection=("_id", "type", "source", "target", "uses")
        ):
            if sync["type"] == SyncType.MESSAGES:
                value = f"Messages from <#{sync['source']}> to <#{sync['target']}>\n" \
                        f"(`{sync['uses']}` message(s) transferred)"
            elif sync["type"] == SyncType.ROLE:
                value = f"Role Assignments from <@&{sync['source']}> to <@&{sync['target']}>\n" \
                        f"(`{sync['uses']}` assignment(s) transferred)"
            elif sync["type"] == SyncType.BANS:
                value = f"Bans from `{sync['source']}` to `{sync['target']}`\n" \
                        f"(`{sync['uses']}` ban(s) transferred)"
            else:
                value = f"Unknown sync type"

            fields.append({
                "name": sync["_id"].upper(),
                "value": value
            })

        description = f"Displaying **{(page - 1) * 10 + 1}** - **{min(page * 10, total_count)}** " \
                      f"of **{total_count}** total syncs"
        if total_count > page * 10:
            description += f"\n\nType `/sync list page: {page + 1}` for the next page"

        await ctx.respond(embeds=[dict(
            title="Sync List",
            fields=fields,
            color=Format.INFO.color,
            description=f"{description}\n​"
        )], ephemeral=True)

    @sync.sub_command(extends=dict(
        sync_id="The id of the previously created sync"
    ))
    @guild_only
    @checks.has_permissions_level()
    async def delete(self, ctx, sync_id):
        """
        Delete a sync that is related to this server
        """
        result = await ctx.bot.db.premium.syncs.delete_one({"_id": sync_id.lower(), "guilds": ctx.guild_id})
        if result.deleted_count == 0:
            await ctx.respond(**create_message(
                f"There is **no sync** with the id `{sync_id}` attached to this server.",
                f=Format.ERROR
            ), ephemeral=True)

        else:
            await ctx.respond(**create_message(
                "Successfully **deleted sync**.",
                f=Format.SUCCESS
            ), ephemeral=True)

    async def _check_admin_on(self, guild, user):
        if guild.owner_id == user.id:
            return True

        perms = Permissions.none()
        try:
            member = await self.bot.http.get_guild_member(guild, user)
        except (rest.HTTPNotFound, rest.HTTPForbidden):
            pass
        else:
            perms = guild.compute_permissions(member)

        return perms.administrator

    @sync.sub_command(extends=dict(
        direction=dict(
            choices=SYNC_DIRECTIONS,
            description="The sync direction"
        ),
        channel="The second channel for the sync",
        include=dict(
            choices=[
                ("Only Send", ""),
                ("Send and Edit", "e"),
                ("Send and Delete", "d"),
                ("Send, Edit and Delete", "ed")
            ],
            description="Events that should be synced"
        )
    ))
    @guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("manage_webhooks")
    @checks.cooldown(25, 60 * 30, bucket=checks.CooldownType.AUTHOR, manual=True)
    async def messages(self, ctx, direction, channel, include="ed"):
        """
        Sync new messages from one channel to another
        """
        events = {
            "send": True,
            "edit": "e" in include,
            "delete": "d" in include
        }

        channel_match = re.search(r"[0-9]+", channel)
        if channel_match is None:
            await ctx.respond(**create_message(
                f"`{channel}` is **not a valid channel**. "
                f"Please mention the channel using `#` or use the channel id.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        channel_id = channel_match[0]
        try:
            channel = await ctx.bot.http.get_channel(channel_id)
        except (rest.HTTPNotFound, rest.HTTPForbidden):
            await ctx.respond(**create_message(
                f"**Can't find the channel** with the id `{channel_id}`. "
                f"Are you sure that the bot has access to the channel?",
                f=Format.ERROR
            ), ephemeral=True)
            return

        if channel.id == ctx.channel_id:
            await ctx.respond(**create_message(
                "You can't sync messages between the same channel.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        if channel.type not in {ChannelType.GUILD_NEWS, ChannelType.GUILD_TEXT}:
            await ctx.respond(**create_message(
                f"The channel must be a **text channel**.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        guild = await ctx.bot.http.get_guild(channel.guild_id)
        if guild.id != ctx.guild_id:
            has_admin = await self._check_admin_on(guild, ctx.author)
            if not has_admin:
                await ctx.respond(**create_message(
                    f"You need **administrator permissions** in the target server.",
                    f=Format.ERROR
                ), ephemeral=True)
                return

        async def _create_channel_sync(_source_id, _target_id):
            try:
                webh = await ctx.bot.http.create_webhook(_target_id, name="sync")
            except (rest.HTTPException, asyncio.TimeoutError):
                await ctx.respond(**create_message(
                    "**Can't create a Webhook**, make sure that there are "
                    "less than **10 Webhooks in the target** channel.\n"
                    "If this is the case please wait a bit and try again.",
                    f=Format.ERROR
                ), ephemeral=True)
                return

            sync_id = utils.unique_id()
            doc = await ctx.bot.db.premium.syncs.find_one_and_update(
                {"target": _target_id, "source": _source_id, "type": SyncType.MESSAGES},
                {
                    "$set": {
                        "webhook": webh.to_dict(),
                        "events": events,
                    },
                    "$setOnInsert": {
                        "_id": sync_id,
                        "guilds": [guild.id, ctx.guild_id],
                        "type": SyncType.MESSAGES,
                        "target": _target_id,
                        "source": _source_id,
                        "uses": 0
                    }
                },
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER,
                projection=("_id",)
            )

            sync_id = doc["_id"]
            await ctx.respond(**create_message(
                f"Successfully **created sync** from <#{_source_id}> "
                f"to <#{_target_id}> with the id `{sync_id.upper()}`",
                f=Format.SUCCESS
            ), ephemeral=True)
            await self.bot.db.audit_logs.insert_one({
                "type": AuditLogType.MESSAGE_SYNC_CREATE,
                "timestamp": datetime.utcnow(),
                "guilds": [ctx.guild_id, guild.id],
                "user": ctx.author.id,
                "extra": {"source": _source_id, "target": _target_id, "id": sync_id}
            })

        if "from" in direction:
            await ctx.count_cooldown()
            await _create_channel_sync(channel.id, ctx.channel_id)

        if "to" in direction:
            await ctx.count_cooldown()
            await _create_channel_sync(ctx.channel_id, channel.id)

    @sync.sub_command(extends=dict(
        direction=dict(
            choices=SYNC_DIRECTIONS,
            description="The sync direction"
        ),
        server_id="The id of the second sever"
    ))
    @guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("ban_members")
    @checks.cooldown(1, 30, bucket=checks.CooldownType.AUTHOR, manual=True)
    async def bans(self, ctx, direction, server_id):
        """
        Sync new bans and unbans from one server to another
        """
        try:
            guild = await ctx.bot.http.get_guild(server_id)
        except (rest.HTTPNotFound, rest.HTTPForbidden):
            await ctx.respond(**create_message(
                f"**Can't find the server** with the id `{server_id}`. "
                f"Are you sure that the bot has access to the server?",
                f=Format.ERROR
            ), ephemeral=True)
            return

        if ctx.guild_id == guild.id:
            await ctx.respond(**create_message(
                "You can't sync ban between the same servers.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        has_admin = await self._check_admin_on(guild, ctx.author)
        if not has_admin:
            await ctx.respond(**create_message(
                f"You need **administrator permissions** in the target server.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        async def _create_ban_sync(_source_id, _target_id):
            sync_id = utils.unique_id()
            try:
                await ctx.bot.db.premium.syncs.insert_one({
                    "_id": sync_id,
                    "guilds": [guild.id, ctx.guild_id],
                    "type": SyncType.BANS,
                    "target": _target_id,
                    "source": _source_id,
                    "uses": 0
                })
            except pymongo.errors.DuplicateKeyError:
                await ctx.respond(**create_message(
                    f"There is **already a ban sync** from `{_source_id}` to `{_target_id}`.",
                    f=Format.ERROR
                ), ephemeral=True)
                return

            await ctx.respond(**create_message(
                f"Successfully **created a ban sync** from `{_source_id}` to `{_target_id}` "
                f"with the id `{sync_id.upper()}`.\n"
                f"You can copy all existing bans using `/clipboard copy` and `/clipboard paste options: !* bans`.",
                f=Format.SUCCESS
            ), ephemeral=True)
            await self.bot.db.audit_logs.insert_one({
                "type": AuditLogType.BAN_SYNC_CREATE,
                "timestamp": datetime.utcnow(),
                "guilds": [ctx.guild_id, guild.id],
                "user": ctx.author.id,
                "extra": {"source": _source_id, "target": _target_id, "id": sync_id}
            })

        if "from" in direction:
            await ctx.count_cooldown()
            await _create_ban_sync(guild.id, ctx.guild_id)

        if "to" in direction:
            await ctx.count_cooldown()
            await _create_ban_sync(ctx.guild_id, guild.id)

    @sync.sub_command(extends=dict(
        role_a="The id of the first role on this server",
        direction=dict(
            choices=SYNC_DIRECTIONS,
            description="The sync direction"
        ),
        server_b="The id of the server that the second role belongs to",
        role_b="The id of the second role",
        include=dict(
            choices=[
                ("Only when the role is added", "a"),
                ("Only when the role is removed", "r"),
                ("When the role is added or removed", "ar"),
                ("When the role is added or removed or the member leaves", "arl")
            ],
            description="Events that should be synced"
        )
    ))
    @guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("manage_roles")
    @checks.cooldown(1, 30, bucket=checks.CooldownType.AUTHOR, manual=True)
    async def role(self, ctx, role_a: CommandOptionType.ROLE, direction, server_b, role_b, include="arl"):
        """
        Sync role assignments for one role to another
        """
        events = {
            "add": "a" in include,
            "remove": "r" in include,
            "leave": "l" in include
        }

        try:
            guild = await ctx.bot.http.get_guild(server_b)
        except (rest.HTTPNotFound, rest.HTTPForbidden):
            await ctx.respond(**create_message(
                f"**Can't find the server** with the id `{server_b}`. "
                f"Are you sure that the bot has access to the server?",
                f=Format.ERROR
            ), ephemeral=True)
            return

        if guild.id != ctx.guild_id:
            has_admin = await self._check_admin_on(guild, ctx.author)
            if not has_admin:
                await ctx.respond(**create_message(
                    f"You need **administrator permissions** in the target server.",
                    f=Format.ERROR
                ), ephemeral=True)
                return

        role_a = ctx.resolved.roles.get(role_a)
        if role_a is None:
            await ctx.respond(**create_message(
                f"**Can't find role_a** on this server.",
                f=Format.ERROR
            ))
            return

        role_b = guild.get_role(role_b)
        if role_b is None:
            await ctx.respond(**create_message(
                f"**Can't find role_b** on server_b.",
                f=Format.ERROR
            ))
            return

        if role_a.id == role_b.id:
            if ctx.guild_id == guild.id:
                await ctx.respond(**create_message(
                    "You can't sync assignments between the same roles.",
                    f=Format.ERROR
                ), ephemeral=True)
                return

        async def _create_role_sync(_source_guild_id, _source_role, _target_guild_id, _target_role):
            sync_id = utils.unique_id()

            doc = await ctx.bot.db.premium.syncs.find_one_and_update(
                {"target": _target_role.id, "source": _source_role.id, "type": SyncType.ROLE},
                {
                    "$set": {
                        "events": events,
                    },
                    "$setOnInsert": {
                        "_id": sync_id,
                        "guilds": [ctx.guild_id, guild.id],
                        "type": SyncType.ROLE,
                        "target": _target_role.id,
                        "target_guild": _target_guild_id,
                        "source": _source_role.id,
                        "source_guild": _source_guild_id,
                        "uses": 0
                    }
                },
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER,
                projection=("_id",)
            )

            sync_id = doc["_id"]

            await ctx.respond(**create_message(
                f"Successfully **created sync** from `{_source_role.name}` (`{_source_role.id}`) to "
                f"`{_target_role.name}` (`{_target_role.id}`) with the id `{sync_id.upper()}`",
                f=Format.SUCCESS
            ))
            await self.bot.db.audit_logs.insert_one({
                "type": AuditLogType.ROLE_SYNC_CREATE,
                "timestamp": datetime.utcnow(),
                "guilds": [ctx.guild_id, guild.id],
                "user": ctx.author.id,
                "extra": {"source": _source_role.id, "target": _target_role.id, "id": sync_id}
            })

        if "from" in direction:
            await ctx.count_cooldown()
            await _create_role_sync(guild.id, role_b, ctx.guild_id, role_a)

        if "to" in direction:
            await ctx.count_cooldown()
            await _create_role_sync(ctx.guild_id, role_a, guild.id, role_b)
