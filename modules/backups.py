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
import ecies
import base64
import hashlib
import binascii

from .audit_logs import AuditLogType
from . import chatlog
from . import encryption
from util import *

MAX_BACKUPS = {
    PremiumLevel.NONE: 15,
    PremiumLevel.ONE: 50,
    PremiumLevel.TWO: 100,
    PremiumLevel.THREE: 250
}

MAX_MESSAGE_COUNT = {
    PremiumLevel.NONE: 0,
    PremiumLevel.ONE: 50,
    PremiumLevel.TWO: 100,
    PremiumLevel.THREE: 250
}

MIN_INTERVAL = {
    PremiumLevel.NONE: 24,
    PremiumLevel.ONE: 12,
    PremiumLevel.TWO: 8,
    PremiumLevel.THREE: 4
}

INTERVAL_KEEP = {
    PremiumLevel.NONE: 1,
    PremiumLevel.ONE: 2,
    PremiumLevel.TWO: 4,
    PremiumLevel.THREE: 8
}


def channel_tree(channels):
    result = ""
    channels = sorted(channels, key=lambda c: (c.type == ChannelType.GUILD_VOICE, c.position))

    def _format_channel(channel, spacing=0):
        prefixes = {
            ChannelType.GUILD_TEXT: "#",
            ChannelType.GUILD_VOICE: "<",
            ChannelType.GUILD_CATEGORY: "\n˅",
            ChannelType.GUILD_NEWS: "!",
            ChannelType.GUILD_STORE: "$",
            ChannelType.GUILD_STAGE: ")"
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


option_descriptions = dict(
    delete_roles="All **existing roles** will be **deleted**",
    delete_channels="All **existing channels** will be **deleted**",
    roles="New roles will be loaded",
    channels="New channels will be loaded",
    settings="Server settings will be updated",
    members="Member roles and nicknames will be loaded",
    messages="Messages will be loaded"
)


def option_list(options):
    result = []
    for option, value in option_descriptions.items():
        if option in options:
            result.append(f"- {value}")

    return "\n".join(result)


def option_status_list(options):
    result = []
    for option, value in option_descriptions.items():
        status = options.get(option)
        if status is None:
            continue

        text = value.replace("**", "")
        if status.state == backups_pb2.LoadStatus.State.RUNNING:
            result.append(f"**- {text}**")
        elif status.state == backups_pb2.LoadStatus.State.RATE_LIMIT:
            result.append(f"**- {text}** ⚠️")
        else:
            result.append(f"- {text}")

    return "\n".join(result)


def convert_v1_to_v2(data):
    channels = []
    for channel in data["channels"]:
        channels.append(
            backups_pb2.BackupData.Channel(
                id=channel["id"],
                type=channel["type"],
                name=channel["name"],
                position=channel["position"],
                overwrites=[
                    backups_pb2.BackupData.Channel.Overwrite(
                        id=ov["id"],
                        type=ov["type"] if isinstance(ov["type"], int) else int(ov["type"] != "role"),
                        allow=str(ov["allow"]),
                        deny=str(ov["deny"])
                    )
                    for ov in channel["permission_overwrites"]
                ],
                parent_id=channel.get("parent_id"),

                topic=channel.get("topic"),
                nsfw=channel.get("nsfw"),
                rate_limit_per_user=channel.get("rate_limit_per_user"),
                chatlog=chatlog.convert_v1_to_v2(channel["messages"]) if "messages" in channel else None,

                bitrate=channel.get("bitrate"),
                user_limit=channel.get("user_limit")
            )
        )

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
        members={
            member["id"]: backups_pb2.BackupData.Member(
                nick=member["nick"],
                roles=member["roles"]
            )
            for member in data.get("members", [])
        }
    )


def parse_options(default, allowed, option_string):
    options = set(default)

    for option in option_string.lower().replace("-", "_").split(" "):
        if option == "!*":
            options.clear()
        elif option == "*":
            options = set(allowed)
        elif option.startswith("!"):
            try:
                options.remove(option[1:])
            except KeyError:
                pass
        elif option in allowed:
            options.add(option)

    return options


class BackupsModule(Module):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grid_fs = AsyncIOMotorGridFSBucket(self.bot.db, "backup_chunks", chunk_size_bytes=8000000)

    async def post_setup(self):
        pass

    @Module.command()
    async def backup(self, ctx):
        """
        Create, load and manage your server backups
        """

    @backup.sub_command(extends=dict(
        message_count="The count of messages to save per channel (default max)"
    ))
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("administrator")
    @checks.cooldown(1, 30, bucket=checks.CooldownType.GUILD, manual=True)
    async def create(self, ctx, message_count: int = 250):
        """
        Create a backup of this server

        Get more help on the [wiki](https://wiki.xenon.bot/backups#creating-a-backup).
        """
        max_backups = MAX_BACKUPS[ctx.premium_level]
        max_message_count = MAX_MESSAGE_COUNT[ctx.premium_level]
        message_count = min(message_count, max_message_count)

        backup_count = await ctx.bot.db.backups.count_documents({"creator": ctx.author.id})
        if backup_count > max_backups:
            await ctx.respond(**create_message(
                f"You have **exceeded the maximum count** of backups. (`{backup_count}/{max_backups}`)\n"
                f"You need to **delete old backups** with `/backup delete` or **buy "
                f"[Xenon Premium](https://www.patreon.com/merlinfuchs)** to create new backups.\n\n"
                f"*Type `/backup list` to view your backups.*",
                f=Format.ERROR
            ), ephemeral=True)
            return

        await ctx.count_cooldown()
        await ctx.respond(**create_message(
            "Creating backup ...",
            f=Format.PLEASE_WAIT
        ), ephemeral=True)

        try:
            replies = await self.bot.rpc.backups.Create(backups_pb2.CreateRequest(
                guild_id=ctx.guild_id,
                options=["roles", "channels", "settings", "members", "bans", "messages"],
                message_count=message_count
            ))
        except GRPCError as e:
            if e.status == grpclib.Status.NOT_FOUND:
                await ctx.edit_response(**create_message(
                    f"Xenon doesn't seem to be on this server, "
                    f"please click [here](https://xenon.bot/invite) to invite it again.",
                    f=Format.ERROR
                ))
                return
            else:
                raise

        data = replies[-1].data
        backup_id = await self._store_backup(ctx.author.id, data)

        await ctx.edit_response(**create_message(
            f"Successfully **created backup** with the id `{backup_id}`.\n\n"
            f"**Usage**\n"
            f"```/backup info backup_id: {backup_id}```"
            f"```/backup load backup_id: {backup_id}```",
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

    @backup.sub_command(extends=dict(
        backup_id="The id of the previously created backup",
        message_count="The count of messages to load per channel (default max)",
        options="A list of options"
    ))
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    @checks.not_in_maintenance
    @checks.cooldown(1, 5 * 60, bucket=checks.CooldownType.GUILD, manual=True)
    async def load(self, ctx, backup_id, message_count: int = 250, options: str.lower = ""):
        """
        Load a previously created backup on this server

        Get more help on the [wiki](https://wiki.xenon.bot/backups#loading-a-backup).
        """
        max_message_count = MAX_MESSAGE_COUNT[ctx.premium_level]
        message_count = min(message_count, max_message_count)

        props, data = await self._retrieve_backup(ctx.author.id, backup_id)
        if data is None:
            await ctx.respond(**create_message(
                f"You have **no backup** with the id `{backup_id}`.\n\n"
                f"*Keep in mind that you can only access your own backups.*",
                f=Format.ERROR
            ), ephemeral=True)
            return

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
                f"Due to a **Discord limitation** the bot is **not able to load this backup** at the moment.\n\n"
                f"You have to wait **{timedelta_to_string(timedelta(seconds=rl.delta))}** "
                f"before you can load a backup containing this many roles again.\n\n"
                f"You can also load this backup without roles using"
                f"```/backup load backup_id: {backup_id} options: !delete_roles !roles```",
                f=Format.ERROR
            ), ephemeral=True)
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
            except rest.HTTPException:
                pass
            return

        await ctx.count_cooldown()

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.BACKUP_LOAD,
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
            ids = translator.get("ids", {})

        await ctx.edit_response(**create_message(
            "**The backup will start loading now**. Please be patient, this can take a while!\n\n"
            "Use `/backup status` to get the current status and `/backup cancel` to cancel the process.\n\n"
            "*This message might not be updated.*",
            f=Format.INFO
        ))

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
            elif e.status == grpclib.Status.NOT_FOUND:
                await ctx.edit_response(**create_message(
                    f"Xenon doesn't seem to be on this server, "
                    f"please click [here](https://xenon.bot/invite) to invite it again.",
                    f=Format.ERROR
                ))
                return
            elif e.status == grpclib.Status.RESOURCE_EXHAUSTED:
                await ctx.edit_response(**create_message(
                    f"Xenon is currently experiencing increased load and can't process your request, "
                    f"please **try again in a few minutes**.",
                    f=Format.ERROR
                ))
                return
            elif e.status == grpclib.Status.CANCELLED:
                return
            else:
                raise

        try:
            await ctx.edit_response(**create_message(
                f"Successfully **loaded the backup**.",
                f=Format.SUCCESS
            ))
        except rest.HTTPException:
            pass

        # Save ids for later use and recovery
        if len(replies[-1].ids) > 0:
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

    @backup.sub_command()
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.cooldown(2, 30, bucket=checks.CooldownType.GUILD)
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
                ), ephemeral=True)
                return
            else:
                raise

        await ctx.respond(**create_message(
            "Successfully **cancelled the currently running loading process** on this server.",
            f=Format.SUCCESS
        ), ephemeral=True)

    @backup.sub_command()
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.cooldown(2, 10, bucket=checks.CooldownType.GUILD)
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
                ), ephemeral=True)
                return
            else:
                raise

        estimated_time_left = sum([
            o.estimated_time_left
            for o in reply.options.values()
            if o.state != backups_pb2.LoadStatus.State.WAITING
        ])

        minutes = estimated_time_left // 60
        seconds = estimated_time_left % 60
        if minutes == 0:
            etl = "< 1 minute"
        else:
            etl = timedelta_to_string(timedelta(minutes=minutes + int(seconds > 0)))

        details = "\n\n" + "\n".join([f"```{o.details}```" for o in reply.options.values() if o.details])
        for o in reply.options.values():
            if o.state == backups_pb2.LoadStatus.State.RATE_LIMIT:
                details += f"\n```A long lasting ratelimit has been hit, " \
                           f"you might want to cancel the loading process.```"
                break

        await ctx.respond(**create_message(
            f"Estimated time required for this step: `{etl}`\n\n"
            f"Type `/backup cancel` to cancel the loading process.\n\n"
            f"{option_status_list(reply.options)}"
            f"{details}",
            title="Loading Status",
            f=Format.INFO
        ), ephemeral=True)

    @backup.sub_command(
        extends=dict(
            backup_id="The id of the previously created backup"
        )
    )
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def info(self, ctx, backup_id):
        """
        Get information about a previously created backup
        """
        props, data = await self._retrieve_backup(ctx.author.id, backup_id)
        if data is None:
            await ctx.respond(**create_message(
                f"You have **no backup** with the id `{backup_id}`.\n\n"
                f"*Keep in mind that you can only access your own backups.*",
                f=Format.ERROR
            ), ephemeral=True)
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
        }], ephemeral=True)

    @backup.sub_command(extends=dict(
        page="The page to display (default 1)",
        master_kay="The master key (only for encrypted backups)"
    ))
    @checks.cooldown(2, 10, bucket=checks.CooldownType.AUTHOR)
    async def list(self, ctx, page: int = 1, master_key=None):
        """
        Get a list of all your previously created backups
        """
        page = max(page, 1)
        _filter = {"creator": ctx.author.id}
        total_count = await self.bot.db.backups.count_documents(_filter)
        if total_count == 0:
            await ctx.respond(**create_message(
                "You **don't have any backups** yet. Use `/backup create` to create one.",
                f=Format.INFO
            ), ephemeral=True)
            return

        if master_key is not None:
            try:
                master_key = base64.b32decode(master_key + "====")
            except binascii.Error:
                master_key = None

        fields = []
        contains_encrypted = False
        async for backup in self.bot.db.backups.find(
                _filter,
                sort=[("timestamp", pymongo.DESCENDING)],
                limit=10,
                skip=(page - 1) * 10,
                projection=("_id", "timestamp", "interval", "encrypted", "large", "data.id", "data.name", "data.key")
        ):
            properties = []
            if backup.get("interval"):
                properties.append("⏲️")

            if backup.get("encrypted"):
                properties.append("🔒")

            if backup.get("large"):
                properties.append("🐘")

            backup_id = backup['_id'].upper()
            if backup.get("encrypted"):
                backup_id = "encrypted"
                if master_key is not None:
                    try:
                        backup_id = encryption.key_to_id(ecies.decrypt(master_key, backup["data"]["key"]))
                    except (binascii.Error, ValueError):
                        contains_encrypted = True
                else:
                    contains_encrypted = True

            fields.append(dict(
                name=backup_id + f" • {' '.join(properties)}" * (len(properties) > 0),
                value=f"{backup['data']['name']} (`{datetime_to_string(backup['timestamp'])} UTC`)"
            ))

        description = f"Displaying **{(page - 1) * 10 + 1}** - **{min(page * 10, total_count)}** " \
                      f"of **{total_count}** total backups"
        if contains_encrypted:
            description += f"\n\n*Some backups are encrypted, supply the master key to see the backup ids.*"
        if total_count > page * 10:
            description += f"\n\nType `/backup list page: {page + 1}` for the next page"

        await ctx.respond(embeds=[dict(
            title="Backup List",
            fields=fields,
            color=Format.INFO.color,
            description=f"{description}\n​"
        )], ephemeral=True)

    @backup.sub_command(
        extends=dict(
            backup_id="The id of the previously created backup"
        )
    )
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def delete(self, ctx, backup_id):
        """
        Delete a previously created backup >THIS CAN NOT BE UNDONE<

        Get more help on the [wiki](https://wiki.xenon.bot/backups#deleting-a-backup).
        """
        if len(backup_id) > 20:
            try:
                key_bytes = encryption.id_to_key(backup_id)
            except binascii.Error:
                pass
            else:
                backup_id = base64.b64encode(hashlib.sha3_512(key_bytes).digest()).decode()

        result = await self._delete_backup(ctx.author.id, backup_id)
        if result:
            await ctx.respond(**create_message(
                "Successfully **deleted backup**.",
                f=Format.SUCCESS
            ), ephemeral=True)

        else:
            await ctx.respond(**create_message(
                f"You have **no backup** with the id `{backup_id}`.",
                f=Format.ERROR
            ), ephemeral=True)

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
        try:
            td = string_to_timedelta(older_than)
        except OverflowError:
            td = timedelta(seconds=0)

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
            ), ephemeral=True)
            return

        await ctx.respond(**create_message(
            f"Are you sure that you want to delete **{delete_count}** of **{total_count}** total backups?\n\n"
            "Type `/confirm` to confirm this action and continue.",
            f=Format.WARNING
        ), ephemeral=True)

        try:
            await self.bot.wait_for_confirmation(ctx, timeout=60)
        except asyncio.TimeoutError:
            await ctx.edit_response(**create_message(
                f"You action has **timed out**. Use `/backup purge` to try again.",
                f=Format.INFO
            ), ephemeral=True)
            return

        deleted_count = await self._delete_backups(_filter)

        await ctx.count_cooldown()
        await ctx.edit_response(**create_message(
            f"Successfully deleted **{deleted_count}** of **{total_count}** total backups.",
            f=Format.SUCCESS
        ), ephemeral=True)

    @backup.sub_command_group()
    async def interval(self, ctx):
        """
        Manage your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """

    @interval.sub_command()
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.cooldown(2, 10, bucket=checks.CooldownType.AUTHOR)
    async def show(self, ctx):
        """
        Show your current backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        interval = await ctx.bot.db.premium.intervals.find_one({"guild": ctx.guild_id, "user": ctx.author.id})
        if interval is None:
            await ctx.respond(**create_message(
                "The **backup interval is** currently turned **off**.\n"
                "Turn it on with `/backup interval on 24h`.",
                f=Format.ERROR
            ), ephemeral=True)

        else:
            backups = []
            async for backup in self.bot.db.backups.find(
                    {"creator": ctx.author.id, "data.id": ctx.guild_id, "interval": True},
                    sort=[("timestamp", pymongo.DESCENDING)],
                    limit=10,
                    projection=("_id", "timestamp", "encrypted")
            ):
                backup_id = "encrypted" if backup.get("encrypted") else backup["_id"].upper()
                backups.append(f"**{backup_id}** (`{datetime_to_string(backup['timestamp'])} UTC`)")

            await ctx.respond(embeds=[{
                "color": Format.INFO.color,
                "title": "Backup Interval",
                "description": "\n".join(backups) + "\n\nType `/backup list` to get a detailed list of backups.\n​",
                "fields": [
                    {
                        "name": "Interval",
                        "value": timedelta_to_string(timedelta(hours=interval["interval"])),
                        "inline": True
                    },
                    {
                        "name": "Keep",
                        "value": f"the last {interval.get('keep', 1)} backup(s)",
                        "inline": True
                    },
                    {
                        "name": "Message Count",
                        "value": str(interval.get("chatlog", 0)),
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
            }], ephemeral=True)

    @interval.sub_command(
        extends=dict(
            interval=dict(
                description="The interval in which the backups are created (e.g. every 24 hours)",
                choices=(
                        ("4 hours", "4h"),
                        ("8 hours", "8h"),
                        ("12 hours", "12h"),
                        ("24 hours", "24h"),
                        ("2 days", "2d"),
                        ("3 days", "3d"),
                        ("7 days", "3d"),
                        ("14 days", "3d"),
                        ("30 days", "3d")
                )
            ),
            message_count="The count of messages to save per channel (default max)"
        )
    )
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.cooldown(1, 10, bucket=checks.CooldownType.AUTHOR)
    async def on(self, ctx, interval, message_count=250):
        """
        Enable your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        max_message_count = MAX_MESSAGE_COUNT[ctx.premium_level]
        message_count = min(message_count, max_message_count)

        try:
            interval_td = string_to_timedelta(interval)
        except OverflowError:
            interval_td = timedelta(hours=24)

        hours = max(interval_td.total_seconds() // 3600, MIN_INTERVAL[ctx.premium_level])
        interval_td = timedelta(hours=hours)

        now = datetime.utcnow()
        await ctx.bot.db.premium.intervals.update_one({"guild": ctx.guild_id, "user": ctx.author.id}, {"$set": {
            "guild": ctx.guild_id,
            "user": ctx.author.id,
            "last": now,
            "next": now,
            "interval": hours,
            "keep": INTERVAL_KEEP[ctx.premium_level],
            "chatlog": message_count
        }}, upsert=True)

        await ctx.respond(**create_message(
            "Successful **enabled the backup interval**.\nThe first backup will be created in "
            f"`{timedelta_to_string(interval_td)}` "
            f"at `{datetime_to_string(now + interval_td)} UTC`.\n\n"
            f"Type `/backup list` to view your interval backups.",
            f=Format.SUCCESS
        ), ephemeral=True)

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.BACKUP_INTERVAL_ENABLE,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

    @interval.sub_command()
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.cooldown(1, 10, bucket=checks.CooldownType.AUTHOR)
    async def off(self, ctx):
        """
        Disable your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        result = await ctx.bot.db.premium.intervals.delete_one({"guild": ctx.guild_id, "user": ctx.author.id})
        if result.deleted_count > 0:
            await ctx.respond(**create_message(
                "Successfully **disabled your backup interval** for this server.",
                f=Format.SUCCESS
            ), ephemeral=True)

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
            ), ephemeral=True)

    async def _retrieve_backup(self, creator, backup_id):
        if len(backup_id) > 20:
            try:
                key_bytes = encryption.id_to_key(backup_id)
            except (binascii.Error, ValueError):
                return None, None
            identifier = base64.b64encode(hashlib.sha3_512(key_bytes).digest()).decode()
            doc = await self.bot.db.backups.find_one({"_id": identifier, "creator": creator})
            if doc is None:
                return None, None

            _, _, key = encryption.get_symmetric_key(key_bytes, doc["data"]["nonce"])
            doc["data"]["raw"] = await self.bot.loop.run_in_executor(None, lambda: key.decrypt(doc["data"]["raw"]))

        else:
            doc = await self.bot.db.backups.find_one({"_id": backup_id.lower(), "creator": creator})
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
        raw = await self.bot.loop.run_in_executor(None, lambda: brotli.compress(data.SerializeToString()))
        backup_id = unique_id().upper()

        doc = {
            "_id": backup_id.lower(),
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

        public_key = await encryption.get_public_key(self.bot, creator)
        if public_key is not None:
            key_bytes, nonce_bytes, symmetric_key = encryption.get_symmetric_key()
            backup_id = encryption.key_to_id(key_bytes)
            doc["_id"] = base64.b64encode(hashlib.sha3_512(key_bytes).digest()).decode()
            doc["encrypted"] = True
            doc["data"]["raw"] = await self.bot.loop.run_in_executor(None, lambda: symmetric_key.encrypt(raw))
            doc["data"]["nonce"] = nonce_bytes
            doc["data"]["key"] = ecies.encrypt(public_key, key_bytes)

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
            {"creator": creator, "_id": backup_id.lower()},
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

    # @Module.task(minutes=20)
    async def interval_task(self):
        tasks = []
        semaphore = asyncio.Semaphore(5)
        to_backup = self.bot.db.premium.intervals.find({"next": {"$lt": datetime.utcnow()}})
        async for interval in to_backup:
            await semaphore.acquire()

            async def _run_interval():
                try:
                    try:
                        replies = await self.bot.rpc.backups.Create(backups_pb2.CreateRequest(
                            guild_id=interval["guild"],
                            options=["roles", "channels", "settings"]
                        ))
                    except GRPCError as e:
                        if e.status == grpclib.Status.NOT_FOUND:
                            await self.bot.db.premium.intervals.delete_many({"guild": interval["guild"]})
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
