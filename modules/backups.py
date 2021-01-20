import dc_interactions as dc
import asyncio
from xenon import *
from xenon import rest
from xenon.cmd import *
import pymongo
import pymongo.errors
from datetime import datetime, timedelta

from .audit_logs import AuditLogType

MAX_BACKUPS = 15


class BackupListMenu(ListMenu):
    embed_kwargs = {"title": "Your Backups"}
    per_page = 10

    async def get_items(self):
        args = {
            "limit": self.per_page,
            "skip": self.page * 10,
            "sort": [("timestamp", pymongo.DESCENDING)],
            "filter": {
                "creator": self.ctx.author.id,
            }
        }

        if self.options.get("guild_scoped"):
            args["filter"]["data.id"] = self.ctx.guild_id

        backups = self.ctx.bot.db.backups.find(**args)
        items = []
        async for backup in backups:
            items.append((
                backup["_id"].upper() + (" ⏲️" if backup.get("interval") else ""),
                f"{backup['data']['name']} (`{datetime_to_string(backup['timestamp'])} UTC`)"
            ))

        return items


class BackupsModule(dc.Module):
    @dc.Module.command()
    async def backup(self, ctx):
        """
        Create, load and manage your server backups
        """

    @backup.sub_command()
    @checks.has_permissions_level()
    @checks.cooldown(1, 10, bucket=checks.CooldownType.GUILD, manual=True)
    async def create(self, ctx):
        """
        Create a backup of this server

        Get more help on the [wiki](https://wiki.xenon.bot/backups#creating-a-backup).
        """
        backup_count = await ctx.bot.db.backups.count_documents({"creator": ctx.author.id})
        if backup_count > MAX_BACKUPS:
            await ctx.respond_with_source(**create_message(
                f"You have **exceeded the maximum count** of backups. (`{backup_count}/{MAX_BACKUPS}`)\n"
                f"You need to **delete old backups** with `/backup delete` or **buy "
                f"[Xenon Premium](https://www.patreon.com/merlinfuchs)** to create new backups.\n\n"
                f"*You can view your current backups by doing `/backup list`.*",
                f=Format.ERROR
            ))
            return

        await ctx.count_cooldown()
        await ctx.respond_with_source(**create_message("Creating backup ...", f=Format.PLEASE_WAIT))

        saver = GuildSaver(self.bot, ctx.guild_id)
        async for status, coro in saver.save(members=False, messages=False, chatlog=0):
            await asyncio.sleep(0.5)
            await coro

        backup_id = await self._store_backup(ctx.author.id, saver.data)

        await asyncio.sleep(1)
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
            backup_id=dict(
                description="The id of the previously created backup"
            ),
            options=dict(
                description="An optional list of options"
            )
        )
    )
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    @checks.not_in_maintenance
    @checks.cooldown(1, 60, bucket=checks.CooldownType.GUILD, manual=True)
    async def load(self, ctx, backup_id: str.lower, options=""):
        """
        Load a previously created backup on this server

        Get more help on the [wiki](https://wiki.xenon.bot/backups#loading-a-backup).
        """
        backup = await self._retrieve_backup(ctx.author.id, backup_id)
        if backup is None:
            await ctx.respond_with_source(**create_message(
                f"You have **no backup** with the id `{backup_id.upper()}`.\n\n"
                f"*Keep in mind that you can only access your own backups.*",
                f=Format.ERROR
            ))
            return

        if await ctx.bot.redis.exists(f"cmd:loaders:{ctx.guild_id}"):
            await ctx.respond_with_source(**create_message(
                "There is **already** a backup or template loader **running**. "
                "You can't start more than one at the same time.\n"
                "You have to **wait until it's done** or use `/backup cancel` to cancel the loader..",
                f=Format.ERROR
            ))
            return

        await ctx.ack_with_source()
        await asyncio.sleep(0.2)

        # Fill options object
        parsed_options = LoaderOptions("delete-channels delete-roles channels roles bans settings")
        parsed_options.update(options)
        parsed_options.update("!messages !members")

        # Require a confirmation by the user
        status_msg = Message(await ctx.respond(**create_message(
            warning_text(parsed_options),
            f=Format.WARNING
        )))

        confirmed = await reaction_confirmation(ctx.bot, status_msg, ctx.author.id)
        if not confirmed:
            await ctx.edit_response(**create_message(
                "You didn't confirm to load the backup so the **loading process was cancelled**.\n"
                f"If this was not intended use `/backup load backup_id: {backup_id}` to try again.",
                f=Format.INFO
            ), message_id=status_msg.id)
            return

        await ctx.count_cooldown()

        # TODO: Publish loaders:start event

        loader = GuildLoader(
            self.bot,
            ctx.guild_id,
            backup["data"],
            options=parsed_options,
            ignore=[ctx.channel_id],
            reason="Backup loaded by " + str(ctx.author)
        )

        # Inject previous id translators if available
        translator = await ctx.bot.db.id_translators.find_one({
            "target_id": ctx.guild_id,
            "source_id": loader.data["id"]
        })
        if translator is not None:
            loader.ids.update(translator["ids"])

        try:
            async for option in run_loader(loader):
                # TODO: Publish loaders:status event
                try:
                    await ctx.edit_response(**create_message(
                        status_text(parsed_options, option),
                        title="Loading Status",
                        f=Format.PLEASE_WAIT
                    ), message_id=status_msg.id)
                except rest.HTTPException:
                    pass

        except asyncio.CancelledError:
            try:
                await ctx.edit_response(**create_message(
                    "The **loading process was cancelled**.",
                    f=Format.ERROR
                ), message_id=status_msg.id)
            except rest.HTTPException:
                pass

        except RoleRateLimit as e:
            remaining = timedelta(hours=48)
            if e.ratelimit is not None:
                remaining = timedelta(seconds=e.ratelimit.delta)

            try:
                await ctx.edit_response(**create_message(
                    "Seems like you **hit** the `250 per 48 hours` **role creation limit** of discord.\n"
                    "Xenon is only allowed to create 250 roles in a time frame of 48 hours.\n\n"
                    f"**You have to wait** `{timedelta_to_string(remaining, precision='m')}` "
                    f"before loading another backup or template containing roles.\n\n"
                    f"**This is a discord limitation and there is no way around it.**",
                    f=Format.ERROR
                ), message_id=status_msg.id)
            except rest.HTTPException:
                pass

        else:
            try:
                await ctx.edit_response(**create_message(
                    f"Successfully **loaded the backup**.",
                    f=Format.SUCCESS
                ), message_id=status_msg.id)
            except rest.HTTPException:
                pass

            if parsed_options.get("delete_channels"):
                await asyncio.sleep(5)
                try:
                    await ctx.bot.http.delete_channel(ctx.channel_id)
                except rest.HTTPException:
                    pass

        # Save ids for later use and recovery
        await ctx.bot.db.id_translators.update_one(
            {
                "target_id": ctx.guild_id,
                "source_id": loader.data["id"],
            },
            {
                "$set": {
                    "target_id": ctx.guild_id,
                    "source_id": loader.data["id"],
                    **{
                        f"ids.{s}": t
                        for s, t in loader.ids.items()
                    }
                },
                "$addToSet": {
                    "loaders": ctx.author.id
                }
            },
            upsert=True
        )

        # TODO: Publish loaders:done event

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.BACKUP_LOAD,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

    @backup.sub_command()
    @checks.has_permissions_level(destructive=True)
    async def cancel(self, ctx):
        """
        Cancel the currently running loading process on this server
        """
        await ctx.bot.redis.delete(f"cmd:loaders:{ctx.guild_id}")
        await ctx.respond_with_source(**create_message(
            "Successfully **cancelled the currently running loader** on this server.",
            f=Format.SUCCESS
        ))

    @backup.sub_command()
    @checks.has_permissions_level()
    async def status(self, ctx):
        """
        Get the status of the currently running loader
        """
        status = await ctx.bot.redis.get(f"cmd:loaders:{ctx.guild_id}")
        if status is None:
            await ctx.respond_with_source(**create_message(
                "There is currently no loader running on this server",
                f=Format.ERROR
            ))
            return

        status_text = option_text[status.decode()]
        await ctx.respond_with_source(**create_message(
            f"{status_text} ...\n\n"
            f"*Please be patient, this could take a while.*",
            title="Loader Status",
            f=Format.INFO
        ))

    @backup.sub_command(
        extends=dict(
            backup_id=dict(
                description="The id of the previously created backup"
            ),
        )
    )
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def info(self, ctx, backup_id: str.lower):
        """
        Get information about a previously created backup
        """
        backup = await self._retrieve_backup(ctx.author.id, backup_id)
        if backup is None:
            await ctx.respond_with_source(**create_message(
                f"You have **no backup** with the id `{backup_id.upper()}`.\n\n"
                f"*Keep in mind that you can only access your own backups.*",
                f=Format.ERROR
            ))
            return

        data = backup["data"]

        channel_list = channel_tree([Channel(c) for c in data["channels"]])
        if len(channel_list) > 1024:
            channel_list = channel_list[:1000] + "\n...\n```"

        roles = [Role(r) for r in data["roles"]]
        role_list = "```{}```".format("\n".join(
            [r.name for r in sorted(roles, key=lambda r: r.position, reverse=True)]
        ))
        if len(role_list) > 1024:
            role_list = role_list[:1000] + "\n...\n```"

        await ctx.respond_with_source(embeds=[{
            "title": f"Backup Info - *{data['name']}*",
            "color": Format.INFO.color,
            "fields": [
                {
                    "name": "Created At",
                    "value": datetime_to_string(backup["timestamp"]),
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

    @backup.sub_command(
        extends=dict(
            server_only=dict(
                description="Only show backups of this server"
            )
        )
    )
    @checks.cooldown(2, 10, bucket=checks.CooldownType.AUTHOR)
    async def list(self, ctx, server_only: bool = False):
        """
        Get a list of all your previously created backups
        """
        await ctx.ack_with_source()
        await asyncio.sleep(0.2)

        menu = BackupListMenu(ctx, guild_scoped=server_only)
        await menu.start()

    @backup.sub_command(
        extends=dict(
            backup_id=dict(
                description="The id of the previously created backup"
            ),
        )
    )
    @checks.cooldown(5, 30, bucket=checks.CooldownType.AUTHOR)
    async def delete(self, ctx, backup_id: str.lower):
        """
        Delete a previously created backup >THIS CAN NOT BE UNDONE<

        Get more help on the [wiki](https://wiki.xenon.bot/backups#deleting-a-backup).
        """
        result = await ctx.bot.db.backups.delete_one({"_id": backup_id, "creator": ctx.author.id})
        if result.deleted_count > 0:
            await ctx.respond_with_source(**create_message(
                "Successfully **deleted backup**.",
                f=Format.SUCCESS
            ))

        else:
            await ctx.respond_with_source(**create_message(
                f"You have **no backup** with the id `{backup_id.upper()}`.",
                f=Format.ERROR
            ))

    @backup.sub_command(
        extends=dict(
            older_than=dict(
                description="Only backups that are older than this will be deleted (e.g. 24h)"
            ),
            server_name=dict(
                description="Only backups matching the server name will be deleted (e.g. 'My Server')"
            )
        )
    )
    @checks.cooldown(1, 30, bucket=checks.CooldownType.AUTHOR, manual=True)
    async def purge(self, ctx, older_than="", server_name=None):
        """
        Delete all (or some) of your backups >THIS CAN NOT BE UNDONE<
        """
        await ctx.ack_with_source()
        await asyncio.sleep(0.2)

        warning_msg = Message(await ctx.respond(**create_message(
            "Are you sure that you want to delete all (or some) of your backups?\n"
            "__**This cannot be undone!**__",
            f=Format.WARNING
        )))

        confirmed = await reaction_confirmation(ctx.bot, warning_msg, ctx.author.id)
        if not confirmed:
            await ctx.edit_response(**create_message(
                "No backups were deleted because you didn't confirm the action.",
                f=Format.INFO
            ), message_id=warning_msg.id)
            return

        td = string_to_timedelta(older_than)
        filter = {
            "creator": ctx.author.id,
            "timestamp": {"$lte": datetime.utcnow() - td}
        }

        if server_name:
            filter["data.name"] = server_name.strip()

        await ctx.count_cooldown()
        result = await ctx.bot.db.backups.delete_many(filter)
        await ctx.edit_response(**create_message(
            f"Successfully **deleted {result.deleted_count} of your backups**.",
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
            await ctx.respond_with_source(**create_message(
                "The **backup interval is** currently turned **off**.\n"
                "Turn it on with `{ctx.bot.prefix}backup interval on 24h`.",
                f=Format.ERROR
            ))

        else:
            await ctx.respond_with_source(embeds=[{
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
            interval=dict(
                description="The interval in which the backups are created (e.g. 24h)"
            )
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

        await ctx.respond_with_source(**create_message(
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
            await ctx.respond_with_source(**create_message(
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
            await ctx.respond_with_source(**create_message(
                f"Your backup interval is not enabled for this server.",
                f=Format.ERROR
            ))

    async def _retrieve_backup(self, creator, backup_id):
        return await self.bot.db.backups.find_one({"_id": backup_id, "creator": creator})

    async def _store_backup(self, creator, data, interval=False):
        backup_id = unique_id()
        await self.bot.db.backups.insert_one({
            "_id": backup_id,
            "creator": creator,
            "timestamp": datetime.utcnow(),
            "data": data,
            "interval": interval
        })
        return backup_id

    @dc.Module.task(minutes=5)
    async def interval_task(self):
        tasks = []
        semaphore = asyncio.Semaphore(5)
        to_backup = self.bot.db.premium.intervals.find({"next": {"$lt": datetime.utcnow()}})
        async for interval in to_backup:
            await semaphore.acquire()

            async def _run_interval():
                try:
                    saver = GuildSaver(self.bot, interval["guild"])
                    try:
                        async for status, coro in saver.save(members=False, messages=False, chatlog=0):
                            await coro
                    except rest.HTTPNotFound:
                        await self.bot.db.intervals.delete_many({"guild": interval["guild"]})

                    await self.bot.db.backups.delete_many({
                        "creator": interval["user"],
                        "data.id": interval["guild"],
                        "interval": True
                    })
                    await self._store_backup(interval["user"], saver.data, interval=True)
                finally:
                    semaphore.release()

            tasks.append(self.bot.create_task(_run_interval()))

        if len(tasks) != 0:
            await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
