from dbots.cmd import *
from dbots import *
import re
from enum import IntEnum

SYNC_DIRECTIONS = [
    ("from", "f"),
    ("to", "t"),
    ("both ways", "ft")
]


class SyncType(IntEnum):
    MESSAGES = 0
    BANS = 1
    ROLE = 2


class SyncModule(Module):
    @Module.command()
    async def sync(self, ctx):
        """
        Sync events from one server or channel to another
        """

    @sync.sub_command()
    @guild_only
    @checks.has_permissions_level()
    async def list(self, ctx):
        """
        List all syncs related to this server
        """

    @sync.sub_command()
    @guild_only
    @checks.has_permissions_level()
    async def delete(self, ctx, sync_id):
        """
        Delete a sync that is related to this server
        """

    def _check_admin_on(self, guild, user):
        perms = Permissions.none()
        try:
            member = self.bot.http.get_guild_member(guild, user)
        except rest.HTTPNotFound:
            pass
        else:
            perms = guild.compute_permissions(member)

        return perms.administrator

    @sync.sub_command(extends=dict(
        direction=dict(
            choices=SYNC_DIRECTIONS
        ),
        include=dict(
            choices=[
                ("Only Send", ""),
                ("Send and Edit", "e"),
                ("Send and Delete", "d"),
                ("Send, Edit and Delete", "ed")
            ]
        )
    ))
    @guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("manage_webhooks")
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
            ))
            return

        channel_id = channel_match[0]
        try:
            channel = await ctx.bot.http.get_channel(channel_id)
        except rest.HTTPNotFound:
            await ctx.respond(**create_message(
                f"**Can't find the channel** with the id `{channel_id}`. "
                f"Are you sure that the bot has access to the channel?",
                f=Format.ERROR
            ))
            return

        if channel.type not in {ChannelType.GUILD_NEWS, ChannelType.GUILD_TEXT}:
            await ctx.respond(**create_message(
                f"The channel must be a **text channel**.",
                f=Format.ERROR
            ))
            return

        guild = await ctx.bot.http.get_guild(channel.guild_id)
        if guild.id != ctx.guild_id:
            has_admin = self._check_admin_on(guild, ctx.author)
            if not has_admin:
                await ctx.respond(**create_message(
                    f"You need **administrator permissions** in the target server.",
                    f=Format.ERROR
                ))
                return

        async def _create_channel_sync(_source_id, _target_id):
            try:
                webh = await ctx.bot.http.create_webhook(_target_id, name="sync")
            except rest.HTTPException:
                raise

            sync_id = utils.unique_id()
            result = await ctx.bot.db.premium.syncs.update_one(
                {"target": _target_id, "source": _source_id},
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
                upsert=True
            )

            if result.upserted_id:
                pass
            
            else:
                pass

        if "f" in direction:
            await _create_channel_sync(channel.id, ctx.channel_id)

        if "t" in direction:
            await _create_channel_sync(ctx.channel_id, channel.id)

    @sync.sub_command(extends=dict(
        direction=dict(
            choices=SYNC_DIRECTIONS
        )
    ))
    @guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("ban_members")
    async def bans(self, ctx, direction, server):
        """
        Sync new bans and unbans from one server to another
        """

    @sync.sub_command(extends=dict(
        direction=dict(
            choices=SYNC_DIRECTIONS
        )
    ))
    @guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("manage_roles")
    async def role(self, ctx, role_a, direction, server_b, role_b):
        """
        Sync role assignments for one role to another
        """
