from dbots.cmd import *
from dbots import *
from dbots.protos import backups_pb2
from datetime import datetime, timedelta
import brotli
import asyncio
import grpclib
from grpclib.exceptions import GRPCError

from .backups import MAX_MESSAGE_COUNT, channel_tree, parse_options, option_list
from .audit_logs import AuditLogType


class ClipboardModule(Module):
    @Module.command()
    async def clipboard(self, ctx):
        """
        Save, load and manage your clipboard (similar to ctrl+c & ctrl+v)
        """

    @clipboard.sub_command(extends=dict(
        message_count="The count of messages to save per channel"
    ))
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("administrator")
    @checks.cooldown(1, 30, bucket=checks.CooldownType.GUILD)
    async def copy(self, ctx, message_count: int = 250):
        """
        Save this server to your clipboard
        """
        max_message_count = MAX_MESSAGE_COUNT[ctx.premium_level]
        message_count = min(message_count, max_message_count)
        await ctx.respond(**create_message("Saving to clipboard ...", f=Format.PLEASE_WAIT))

        replies = await self.bot.rpc.backups.Create(backups_pb2.CreateRequest(
            guild_id=ctx.guild_id,
            options=["roles", "channels", "settings", "members", "bans", "messages"],
            message_count=message_count
        ))

        data = replies[-1].data
        raw = await self.bot.loop.run_in_executor(None, lambda: brotli.compress(data.SerializeToString()))
        await ctx.bot.redis.setex(f"clipboard:{ctx.author.id}", 60 * 60, raw)

        await ctx.edit_response(**create_message(
            f"Successfully **copied this server to the clipboard**. "
            f"Your clipboard will be automatically cleared after one hour.\n\n"
            f"**Usage**\n"
            f"```/clipboard view```"
            f"```/clipboard paste```",
            f=Format.SUCCESS
        ))

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.COPY,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

    @clipboard.sub_command(extends=dict(
        message_count="The count of messages to load per channel",
        options="A list of options"
    ))
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    @checks.not_in_maintenance
    @checks.cooldown(1, 5 * 60, bucket=checks.CooldownType.GUILD, manual=True)
    async def paste(self, ctx, message_count: int = 250, options=""):
        """
        Load the server from your clipboard on this server
        """
        max_message_count = MAX_MESSAGE_COUNT[ctx.premium_level]
        message_count = min(message_count, max_message_count)

        raw = await ctx.bot.redis.get(f"clipboard:{ctx.author.id}")
        if raw is None:
            await ctx.respond(**create_message(
                "There is **nothing on your clipboard**. Type `/clipboard copy` to save a server to your clipboard.",
                f=Format.ERROR
            ))
            return

        data = backups_pb2.BackupData()
        await self.bot.loop.run_in_executor(None, lambda: data.ParseFromString(brotli.decompress(raw)))

        parsed_options = parse_options(
            ("delete_roles", "delete_channels", "roles", "channels", "settings", "members", "bans", "messages"),
            ("delete_roles", "delete_channels", "roles", "channels",
             "update", "settings", "members", "bans", "messages", "pins"),
            options
        )

        role_route = rest.Route("POST", "/guilds/{guild_id}/roles", guild_id=ctx.guild_id)
        rl = await ctx.bot.http.get_bucket(role_route.bucket)
        if rl is not None and rl.remaining < len(data.roles) and "roles" in parsed_options:
            await ctx.respond(**create_message(
                f"Due to a **Discord limitation** the bot is **not able to load this server** at the moment.\n\n"
                f"You have to wait **{timedelta_to_string(timedelta(seconds=rl.delta))}** "
                f"before you can load a server containing this many roles again.\n\n"
                f"You can also load this server without roles using"
                f"```/clipboard paste options: !delete_roles !roles```",
                f=Format.ERROR
            ))
            return

            # Require a confirmation by the user
        await ctx.respond(**create_message(
            "**Hey, be careful!** The following actions will be taken on this server and **can not be undone**:\n\n"
            f"{option_list(parsed_options)}\n\n"
            f"Type `/confirm` to confirm this action and continue.",
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

        # await ctx.count_cooldown()

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.COPY,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

        ids = {}
        translator = await ctx.bot.db.id_translators.find_one({
            "target_id": ctx.guild_id,
            "source_id": data.id
        })
        if translator is not None:
            ids = translator["ids"]

        await ctx.edit_response(**create_message(
            "**The server will start loading now**. Please be patient, this can take a while!\n\n"
            "Use `/backup status` to get the current status and `/backup cancel` to cancel the process.\n\n"
            "*This message might not be updated.*",
            f=Format.INFO
        ))
        await asyncio.sleep(10)

        try:
            replies = await self.bot.rpc.backups.Load(backups_pb2.LoadRequest(
                guild_id=ctx.guild_id,
                options=list(parsed_options),
                message_count=message_count,
                data=data,
                reason="Backup loaded by " + str(ctx.author),
                ids=ids
            ))
        except GRPCError as e:
            if e.status == grpclib.Status.ALREADY_EXISTS:
                await ctx.edit_response(**create_message(
                    f"There is **already a loading process running** on this server.\n"
                    f"Please wait for it to finish or use `/backup cancel` to stop it.",
                    f=Format.ERROR
                ))
                return
            elif e.status == grpclib.Status.CANCELLED:
                return
            else:
                raise

        try:
            await ctx.edit_response(**create_message(
                f"Successfully **loaded the server from the clipboard**.",
                f=Format.SUCCESS
            ))
        except rest.HTTPNotFound:
            pass

        # Save ids for later use and recovery
        await ctx.bot.db.id_translators.update_one(
            {
                "target_id": ctx.guild_id,
                "source_id": data.id,
            },
            {
                "$set": {
                    "target_id": ctx.guild_id,
                    "source_id": data.id,
                    **{
                        f"ids.{s}": t
                        for s, t in replies[-1].ids.items()
                    }
                },
                "$addToSet": {
                    "loaders": ctx.author.id
                }
            },
            upsert=True
        )

    @clipboard.sub_command()
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def view(self, ctx):
        """
        Save this server to your clipboard
        """
        raw = await ctx.bot.redis.get(f"clipboard:{ctx.author.id}")
        if raw is None:
            await ctx.respond(**create_message(
                "There is **nothing on your clipboard**. Type `/clipboard copy` to save a server to your clipboard.",
                f=Format.ERROR
            ))
            return

        data = backups_pb2.BackupData()
        await self.bot.loop.run_in_executor(None, lambda: data.ParseFromString(brotli.decompress(raw)))

        channel_list = channel_tree(data.channels)
        if len(channel_list) > 1024:
            channel_list = channel_list[:1000] + "\n...\n```"

        role_list = "```{}```".format("\n".join(
            [r.name for r in sorted(data.roles, key=lambda r: r.position, reverse=True)]
        ))
        if len(role_list) > 1024:
            role_list = role_list[:1000] + "\n...\n```"

        await ctx.respond(embeds=[{
            "title": f"Clipboard Info - *{data.name}*",
            "color": Format.INFO.color,
            "fields": [
                {
                    "name": "Channels",
                    "value": channel_list,
                    "inline": True
                },
                {
                    "name": "Roles",
                    "value": role_list,
                    "inline": True
                },
            ]
        }])

    @clipboard.sub_command()
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def clear(self, ctx):
        """
        Save this server to your clipboard
        """
        await ctx.bot.redis.delete(f"clipboard:{ctx.author.id}")
        await ctx.respond(**create_message(
            "You **clipboard has been cleared**.",
            f=Format.SUCCESS
        ))
