import asyncio
from dbots import *
from dbots.cmd import *
import pymongo
import pymongo.errors
from datetime import datetime, timedelta
from dbots.protos import backups_pb2
from grpclib.exceptions import GRPCError
import grpclib
import brotli
import gridfs
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from .audit_logs import AuditLogType

MAX_BACKUPS = 15


def channel_tree(channels):
    result = ""
    channels = sorted(channels, key=lambda c: (c.type == ChannelType.GUILD_VOICE, c.position))

    def _format_channel(channel, spacing=0):
        prefixes = {
            ChannelType.GUILD_TEXT: "#",
            ChannelType.GUILD_VOICE: ">",
            ChannelType.GUILD_CATEGORY: "\n˅",
            ChannelType.GUILD_NEWS: "!",
            ChannelType.GUILD_STORE: "$"
        }
        return f"{' ' * spacing}{prefixes.get(channel.type, '')} {channel.name}\n"

    for channel in filter(
            lambda c: c.type != ChannelType.GUILD_CATEGORY and not c.parent_id,
            channels
    ):
        result += _format_channel(channel)

    for channel in filter(lambda c: c.type == ChannelType.GUILD_CATEGORY, channels):
        result += _format_channel(channel)
        for child in filter(lambda c: c.parent_id == channel.id, channels):
            result += _format_channel(child, spacing=2)

    return f"```\n{result}\n```"


def warning_list(options):
    warnings = dict(
        delete_roles="All **existing roles** will be **deleted**",
        delete_channels="All **existing channels** will be **deleted**",
        roles="New roles will be loaded",
        channels="New channels will be loaded",
        settings="Server settings will be updated",
        members="Member roles and nicknames will be loaded",
        messages="Some messages will be loaded"
    )
    return "\n".join(
        f"- {value}"
        for option, value in warnings.items()
        if option in options
    )


def convert_v1_to_v2(data):
    channels = []

    return backups_pb2.BackupData(
        id=data["id"],
        name=data["name"],
        icon=data.get("icon"),
        region=data.get("region"),
        afk_channel_id=data.get("afk_channel_id"),
        afk_timeout=data.get("afk_timeout"),
        verification_level=data.get("verification_level"),
        default_message_notifications=data.get("default_message_notifications"),
        explicit_content_filter=data.get("explicit_content_filter"),

        rules_channel_id=data.get("rules_channel_id"),
        public_updates_channel_id=data.get("public_updates_channel_id"),
        preferred_locale=data.get("preferred_locale"),
        splash=data.get("splash"),
        banner=data.get("banner"),

        channels=channels,
        roles=[
            backups_pb2.BackupData.Role(
                id=role["id"],
                name=role["name"],
                permissions=str(role["permissions"]),
                position=role["position"],
                hoist=role.get("hoist"),
                managed=role.get("managed"),
                mentionable=role.get("mentionable"),
                color=role.get("color")
            )
            for role in data.get("roles", [])
        ],
        bans=[
            backups_pb2.BackupData.Ban(
                id=ban["id"],
                reason=ban.get("reason")
            )
            for ban in data.get("bans", [])
        ],
        members=[
            backups_pb2.BackupData.Member(
                id=member["id"],
                nick=member["nick"],
                roles=member["roles"]
            )
            for member in data.get("members", [])
        ]
    )


class BackupsModule(Module):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grid_fs = AsyncIOMotorGridFSBucket(self.bot.db, "backup_chunks", chunk_size_bytes=8000000)

    @Module.command()
    async def backup(self, ctx):
        """
        Create, load and manage your server backups
        """

    @backup.sub_command()
    @checks.has_permissions_level()
    @checks.cooldown(1, 30, bucket=checks.CooldownType.GUILD, manual=True)
    async def create(self, ctx):
        """
        Create a backup of this server

        Get more help on the [wiki](https://wiki.xenon.bot/backups#creating-a-backup).
        """
        backup_count = await ctx.bot.db.backups.count_documents({"creator": ctx.author.id})
        if backup_count > MAX_BACKUPS:
            await ctx.respond(**create_message(
                f"You have **exceeded the maximum count** of backups. (`{backup_count}/{MAX_BACKUPS}`)\n"
                f"You need to **delete old backups** with `/backup delete` or **buy "
                f"[Xenon Premium](https://www.patreon.com/merlinfuchs)** to create new backups.\n\n"
                f"*Type `/backup list` to view your backups.*",
                f=Format.ERROR
            ))
            return

        # await ctx.count_cooldown()
        await ctx.respond(**create_message("Creating backup ...", f=Format.PLEASE_WAIT))

        replies = await self.bot.rpc.backups.Create(backups_pb2.CreateRequest(
            guild_id=ctx.guild_id,
            options=["roles", "channels"],
            message_count=0
        ))

        data = replies[-1].data
        backup_id = await self._store_backup(ctx.author.id, data)

        await ctx.edit_response(**create_message(
            f"Successfully **created backup** with the id `{backup_id.upper()}`.\n\n"
            f"**Usage**\n"
            f"```/backup info backup_id: {backup_id.upper()}```"
            f"```/backup load backup_id: {backup_id.upper()}```",
            f=Format.SUCCESS
        ))

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.BACKUP_CREATE,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

    @backup.sub_command(
        extends=dict(
            backup_id="The id of the previously created backup",
            options="An optional list of options"
        )
    )
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    @checks.not_in_maintenance
    @checks.cooldown(1, 5 * 60, bucket=checks.CooldownType.GUILD, manual=True)
    async def load(self, ctx, backup_id: str.lower, options: str.lower = ""):
        """
        Load a previously created backup on this server

        Get more help on the [wiki](https://wiki.xenon.bot/backups#loading-a-backup).
        """
        props, data = await self._retrieve_backup(ctx.author.id, backup_id)
        if data is None:
            await ctx.respond(**create_message(
                f"You have **no backup** with the id `{backup_id.upper()}`.\n\n"
                f"*Keep in mind that you can only access your own backups.*",
                f=Format.ERROR
            ))
            return

        # Fill options object
        allowed = ("delete_roles", "delete_channels", "roles", "channels", "update")
        parsed_options = {"delete_roles", "delete_channels", "roles", "channels", "settings"}
        for option in options.replace("-", "_").split(" "):
            if option == "!*":
                parsed_options.clear()
            elif option == "*":
                parsed_options = set(allowed)
            elif option.startswith("!"):
                try:
                    parsed_options.remove(option[1:])
                except KeyError:
                    pass
            elif option in allowed:
                parsed_options.add(option)

        # Require a confirmation by the user
        status_msg = await ctx.respond(**create_message(
            "**Hey, be careful!** The following actions will be taken on this server and **can not be undone**:\n\n"
            f"{warning_list(parsed_options)}\n\n"
            f"Type `/confirm` to confirm this action and continue.",
            f=Format.WARNING
        ))

        try:
            await self.bot.wait_for_confirmation(ctx, timeout=60)
        except asyncio.TimeoutError:
            await ctx.delete_response(status_msg.id)
            return

        # await ctx.count_cooldown()

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.BACKUP_LOAD,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

        try:
            async with self.bot.rpc.backups.Load.open() as stream:
                await stream.send_message(backups_pb2.LoadRequest(
                    guild_id=ctx.guild_id,
                    options=list(parsed_options),
                    message_count=0,
                    data=data,
                    reason="Backup loaded by " + str(ctx.author)
                ), end=True)
                async for reply in stream:
                    await ctx.edit_response(**create_message(
                        reply.status,
                        f=Format.PLEASE_WAIT
                    ), message_id=status_msg.id)
        except GRPCError as e:
            if e.status == grpclib.Status.ALREADY_EXISTS:
                await ctx.edit_response(**create_message(
                    f"There is **already a loading process running** on this server.\n"
                    f"Please wait for it to finish or use `/backup cancel` to stop it.",
                    f=Format.ERROR
                ), message_id=status_msg.id)
                return

            else:
                raise

        await ctx.edit_response(**create_message(
            f"Successfully **loaded the backup**.",
            f=Format.SUCCESS
        ), message_id=status_msg.id)

    @backup.sub_command()
    @checks.has_permissions_level(destructive=True)
    async def cancel(self, ctx):
        """
        Cancel the currently running loading process on this server
        """
        try:
            await self.bot.rpc.backups.CancelLoad(backups_pb2.CancelLoadRequest(guild_id=ctx.guild_id))
        except GRPCError as e:
            if e.status == grpclib.Status.NOT_FOUND:
                await ctx.respond(**create_message(
                    "There is **no loading process running** on this server.",
                    f=Format.ERROR
                ))
                return
            else:
                raise

        await ctx.respond(**create_message(
            "Successfully **cancelled the currently running loading process** on this server.",
            f=Format.SUCCESS
        ))

    @backup.sub_command()
    @checks.has_permissions_level()
    async def status(self, ctx):
        """
        Get the status of the currently running loading process
        """
        try:
            reply = await self.bot.rpc.backups.LoadStatus(backups_pb2.LoadStatusRequest(guild_id=ctx.guild_id))
        except GRPCError as e:
            if e.status == grpclib.Status.NOT_FOUND:
                await ctx.respond(**create_message(
                    "There is **no loading process running** on this server.",
                    f=Format.ERROR
                ))
                return
            else:
                raise

        await ctx.respond_with_source(**create_message(
            f"{reply.status} ...\n\n"
            f"*Please be patient, this could take a while.*",
            title="Loader Status",
            f=Format.INFO
        ))

    @backup.sub_command(
        extends=dict(
            backup_id="The id of the previously created backup"
        )
    )
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def info(self, ctx, backup_id: str.lower):
        """
        Get information about a previously created backup
        """
        props, data = await self._retrieve_backup(ctx.author.id, backup_id)
        if data is None:
            await ctx.respond(**create_message(
                f"You have **no backup** with the id `{backup_id.upper()}`.\n\n"
                f"*Keep in mind that you can only access your own backups.*",
                f=Format.ERROR
            ))
            return

        channel_list = channel_tree(data.channels)
        if len(channel_list) > 1024:
            channel_list = channel_list[:1000] + "\n...\n```"

        role_list = "```{}```".format("\n".join(
            [r.name for r in sorted(data.roles, key=lambda r: r.position, reverse=True)]
        ))
        if len(role_list) > 1024:
            role_list = role_list[:1000] + "\n...\n```"

        properties = []
        if props.get("interval"):
            properties.append("⏲️Interval")

        if props.get("large"):
            properties.append("🐘Large")

        if props.get("encrypted"):
            properties.append("🔒Encrypted")

        await ctx.respond(embeds=[{
            "title": f"Backup Info - *{data.name}*",
            "color": Format.INFO.color,
            "footer": {"text": "  ".join(properties)},
            "fields": [
                {
                    "name": "Created At",
                    "value": datetime_to_string(props["timestamp"]),
                    "inline": False
                },
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

    @backup.sub_command()
    @checks.cooldown(2, 10, bucket=checks.CooldownType.AUTHOR)
    async def list(self, ctx, page: int = 1):
        """
        Get a list of all your previously created backups
        """
        _filter = {"creator": ctx.author.id}
        total_count = await self.bot.db.backups.count_documents(_filter)
        if total_count == 0:
            await ctx.respond(**create_message(
                "You **don't have any backups** yet. Use `/backup create` to create one.",
                f=Format.ERROR,
                embed=False
            ), ephemeral=True)
            return

        fields = []
        async for backup in self.bot.db.backups.find(
                _filter,
                sort=[("timestamp", pymongo.DESCENDING)],
                limit=10,
                skip=(page - 1) * 10
        ):
            properties = []
            if backup.get("interval"):
                properties.append("⏲️")

            if backup.get("encrypted"):
                properties.append("🔒")

            if backup.get("large"):
                properties.append("🐘")

            fields.append(dict(
                name=backup['_id'].upper() + f" • {' '.join(properties)}" * (len(properties) > 0),
                value=f"{backup['data']['name']} (`{datetime_to_string(backup['timestamp'])} UTC`)"
            ))

        description = f"Displaying **{(page - 1) * 10 + 1}** - **{min(page * 10, total_count)}** " \
                      f"of **{total_count}** total backups"
        if total_count > page * 10:
            description += f"\n\nType `/backup list {page + 1}` for the next page"

        await ctx.respond(embeds=[dict(
            title="Backup List",
            fields=fields,
            color=Format.INFO.color,
            description=f"{description}\n​"
        )])

    @backup.sub_command(
        extends=dict(
            backup_id="The id of the previously created backup"
        )
    )
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def delete(self, ctx, backup_id: str.lower):
        """
        Delete a previously created backup >THIS CAN NOT BE UNDONE<

        Get more help on the [wiki](https://wiki.xenon.bot/backups#deleting-a-backup).
        """
        result = await self._delete_backup(ctx.author.id, backup_id)
        if result:
            await ctx.respond(**create_message(
                "Successfully **deleted backup**.",
                f=Format.SUCCESS
            ))

        else:
            await ctx.respond(**create_message(
                f"You have **no backup** with the id `{backup_id.upper()}`.",
                f=Format.ERROR
            ))

    @backup.sub_command(
        extends=dict(
            older_than="Only backups that are older than this will be deleted (e.g. 24h)",
            server_name="Only backups matching the server name will be deleted (e.g. 'My Server')"
        )
    )
    @checks.cooldown(1, 30, bucket=checks.CooldownType.AUTHOR, manual=True)
    async def purge(self, ctx, older_than="", server_name=None):
        """
        Delete all (or some) of your backups >THIS CAN NOT BE UNDONE<
        """
        td = string_to_timedelta(older_than)
        _filter = {
            "creator": ctx.author.id,
            "timestamp": {"$lte": datetime.utcnow() - td}
        }
        if server_name:
            _filter["data.name"] = server_name.strip()

        total_count = await self.bot.db.backups.count_documents({"creator": ctx.author.id})
        delete_count = await self.bot.db.backups.count_documents(_filter)

        if delete_count == 0:
            await ctx.respond(**create_message(
                "There are **no backups** to delete.",
                f=Format.ERROR
            ))
            return

        warning_msg = await ctx.respond(**create_message(
            f"Are you sure that you want to delete **{delete_count}** of **{total_count}** total backups?\n\n"
            "Type `/confirm` to confirm this action and continue.",
            f=Format.WARNING
        ))

        try:
            await self.bot.wait_for_confirmation(ctx, timeout=60)
        except asyncio.TimeoutError:
            await ctx.delete_response(warning_msg.id)
            return

        deleted_count = await self._delete_backups(_filter)

        await ctx.count_cooldown()
        await ctx.edit_response(**create_message(
            f"Successfully deleted **{deleted_count}** of **{total_count}** total backups.",
            f=Format.SUCCESS
        ), message_id=warning_msg.id)

    @backup.sub_command_group()
    async def interval(self, ctx):
        """
        Manage your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """

    @interval.sub_command()
    @checks.has_permissions_level()
    @checks.cooldown(2, 10, bucket=checks.CooldownType.AUTHOR)
    async def show(self, ctx):
        """
        Show your current backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        interval = await ctx.bot.db.intervals.find_one({"guild": ctx.guild_id, "user": ctx.author.id})
        if interval is None:
            await ctx.respond(**create_message(
                "The **backup interval is** currently turned **off**.\n"
                "Turn it on with `/backup interval on 24h`.",
                f=Format.ERROR
            ))

        else:
            await ctx.respond(embeds=[{
                "color": Format.INFO.color,
                "title": "Backup Interval",
                "fields": [
                    {
                        "name": "Interval",
                        "value": timedelta_to_string(timedelta(hours=interval["interval"])),
                        "inline": True
                    },
                    {
                        "name": "Last Backup",
                        "value": datetime_to_string(interval["last"]) + " UTC",
                        "inline": False
                    },
                    {
                        "name": "Next Backup",
                        "value": datetime_to_string(interval["next"]) + " UTC",
                        "inline": False
                    }
                ]
            }])

    @interval.sub_command(
        extends=dict(
            interval="The interval in which the backups are created (e.g. 24h)"
        )
    )
    @checks.has_permissions_level()
    @checks.cooldown(1, 10, bucket=checks.CooldownType.AUTHOR)
    async def on(self, ctx, interval="24h"):
        """
        Enable your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        interval_td = string_to_timedelta(interval)
        hours = max(interval_td.total_seconds() // 3600, 24)

        now = datetime.utcnow()
        await ctx.bot.db.intervals.update_one({"guild": ctx.guild_id, "user": ctx.author.id}, {"$set": {
            "guild": ctx.guild_id,
            "user": ctx.author.id,
            "last": now,
            "next": now,
            "interval": hours
        }}, upsert=True)

        await ctx.respond(**create_message(
            "Successful **enabled the backup interval**.\nThe first backup will be created in "
            f"`{timedelta_to_string(interval_td)}` "
            f"at `{datetime_to_string(now + interval_td)} UTC`.",
            f=Format.SUCCESS
        ))

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.BACKUP_INTERVAL_ENABLE,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

    @interval.sub_command()
    @checks.has_permissions_level()
    @checks.cooldown(1, 10, bucket=checks.CooldownType.AUTHOR)
    async def off(self, ctx):
        """
        Disable your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        result = await ctx.bot.db.intervals.delete_one({"guild": ctx.guild_id, "user": ctx.author.id})
        if result.deleted_count > 0:
            await ctx.respond(**create_message(
                "Successfully **disabled your backup interval** for this server.",
                f=Format.SUCCESS
            ))

            # Create audit log entry
            await self.bot.db.audit_logs.insert_one({
                "type": AuditLogType.BACKUP_INTERVAL_DISABLE,
                "timestamp": datetime.utcnow(),
                "guilds": [ctx.guild_id],
                "user": ctx.author.id,
                "extra": {}
            })

        else:
            await ctx.respond(**create_message(
                f"Your backup interval is not enabled for this server.",
                f=Format.ERROR
            ))

    async def _retrieve_backup(self, creator, backup_id):
        doc = await self.bot.db.backups.find_one({"_id": backup_id, "creator": creator})
        if doc is None:
            return None, None

        if doc.get("version") != 2:
            data = convert_v1_to_v2(doc["data"])
            del doc["data"]
            return doc, data

        if doc.get("large"):
            grid_out = await self.grid_fs.open_download_stream(doc["data"]["raw"])
            doc["data"]["raw"] = await grid_out.read()

        data = backups_pb2.BackupData()
        await self.bot.loop.run_in_executor(None, lambda: data.ParseFromString(brotli.decompress(doc["data"]["raw"])))
        del doc["data"]
        return doc, data

    async def _store_backup(self, creator, data, interval=False):
        backup_id = unique_id()
        raw = await self.bot.loop.run_in_executor(None, lambda: brotli.compress(data.SerializeToString()))
        doc = {
            "_id": backup_id,
            "creator": creator,
            "timestamp": datetime.utcnow(),
            "version": 2,
            "interval": interval,
            "encrypted": False,
            "large": False,
            "data": {
                "id": data.id,
                "name": data.name,
                "raw": raw
            },
        }
        try:
            await self.bot.db.backups.insert_one(doc)
        except pymongo.errors.DocumentTooLarge:
            doc["data"]["raw"] = backup_id
            doc["large"] = True
            await self.grid_fs.upload_from_stream_with_id(backup_id, backup_id, raw)
            await self.bot.db.backups.insert_one(doc)

        return backup_id

    async def _delete_backup(self, creator, backup_id):
        doc = await self.bot.db.backups.find_one_and_delete(
            {"creator": creator, "_id": backup_id},
            projection=("large", "_id")
        )
        if doc is None:
            return False

        if doc.get("large"):
            try:
                await self.grid_fs.delete(doc["_id"])
            except gridfs.NoFile:
                pass

        return True

    async def _delete_backups(self, _filter):
        result = await self.bot.db.backups.delete_many({"large": {"$ne": True}, **_filter})
        count = 0
        async for backup in self.bot.db.backups.find(_filter, projection=("creator", "_id")):
            count += 1
            await self._delete_backup(backup["creator"], backup["_id"])

        return result.deleted_count + count

    @Module.task(minutes=5)
    async def interval_task(self):
        tasks = []
        semaphore = asyncio.Semaphore(5)
        to_backup = self.bot.db.intervals.find({"next": {"$lt": datetime.utcnow()}})
        async for interval in to_backup:
            await semaphore.acquire()

            async def _run_interval():
                try:
                    try:
                        replies = await self.bot.rpc.backups.Create(backups_pb2.CreateRequest(
                            guild_id=interval["guild"],
                            options=["roles", "channels"]
                        ))
                    except GRPCError as e:
                        if e.status == grpclib.Status.NOT_FOUND:
                            await self.bot.db.intervals.delete_many({"guild": interval["guild"]})
                            return
                        else:
                            raise

                    data = replies[-1].data
                    if data is None:
                        return

                    await self._delete_backups({
                        "creator": interval["user"],
                        "data.id": interval["guild"],
                        "interval": True
                    })
                    await self._store_backup(interval["user"], data, interval=True)
                finally:
                    semaphore.release()

            tasks.append(self.bot.loop.create_task(_run_interval()))

        if len(tasks) != 0:
            await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
