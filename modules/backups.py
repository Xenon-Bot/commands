from copy import deepcopy
from datetime import datetime, timedelta

from lib.core import *
from lib.discord import *
from . import premium

MAX_BACKUPS = 15
ALLOWED_OPTIONS = ("delete_roles", "delete_channels", "roles", "channels", "settings")
ADVERTISE_OPTIONS = ("bans", "members", "messages")


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
    bans="Banned members will be loaded",
    members="Member roles and nicknames will be loaded",
    messages="Some messages will be loaded"
)

option_names = dict(
    delete_roles="Delete Roles",
    delete_channels="Delete Channels",
    roles="Load Roles",
    channels="Load Channels",
    settings="Load Settings",
    bans="Load Bans",
    members="Load Members",
    messages="Load Messages"
)


def option_list(options):
    result = []
    for option, value in option_descriptions.items():
        if option in options:
            result.append(f"- {value}")

    return "\n".join(result)


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


def create_warning_message(options, state_key, prefix="backup_"):
    return dict(
        **create_message(
            "**Hey, be careful!** The following actions will be taken on this server and **can not be undone**:\n\n"
            f"{option_list(options)}",
            f=Format.WARNING
        ),
        components=[
            ActionRow(
                SelectMenu(
                    *[
                        SelectMenuOption(
                            label=option_names.get(option, option.replace("_", " ").title()),
                            value=option,
                            description=option_descriptions.get(option, "").replace("*", ""),
                            default=option in options
                        )
                        for option in ALLOWED_OPTIONS
                    ],
                    *[
                        SelectMenuOption(
                            label=option_names.get(option, option.replace("_", " ").title()),
                            value=option,
                            description=option_descriptions.get(option, "").replace("*", ""),
                            default=option in options,
                            emoji="⭐"
                        )
                        for option in ADVERTISE_OPTIONS
                    ],
                    max_values=len(ALLOWED_OPTIONS) + len(ADVERTISE_OPTIONS),
                    placeholder="Select Loading Options",
                    custom_id=f"{prefix}load_options",
                    args=[state_key]),
            ),
            ActionRow(
                Button(label="Confirm", style=ButtonStyle.SUCCESS, custom_id=f"{prefix}load_confirm",
                       args=[state_key]),
                Button(label="Cancel", style=ButtonStyle.DANGER, custom_id=f"{prefix}load_cancel", args=[state_key])
            )
        ],
        ephemeral=True
    )


class BackupsModule(Module):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def _unknown_backup_message(self, user_id, backup_id):
        data = deepcopy(create_message(
            f"You have **no backup** with the id `{backup_id}`.\n\n"
            f"*Keep in mind that you can only access your own backups.*",
            f=Format.ERROR
        ))

        select_options = []
        resp = await self.bot.core.backup_list(user_id, limit=25)
        for backup in resp.backups:
            backup_id = backup.id.upper()
            timestamp = datetime_to_string(datetime.fromtimestamp(backup.timestamp))
            select_options.append(SelectMenuOption(
                label=backup_id,
                description=f"{backup.guild_name} ({timestamp})"[:50],
                value=backup_id
            ))

        if len(select_options) != 0:
            data.setdefault("components", []).insert(0, ActionRow(
                SelectMenu(
                    *select_options,
                    placeholder="Select a backup",
                    custom_id="backup_info_direct",
                    min_values=1,
                    max_values=1
                ),
            ))

        data["ephemeral"] = True
        return data

    @Module.command()
    async def backup(self, ctx):
        """
        Create, load and manage your server backups
        """

    @backup.sub_command()
    @checks.guild_only
    async def create(self, ctx):
        """
        Create a backup of this server

        Get more help on the [wiki](https://wiki.xenon.bot/backups#creating-a-backup).
        """
        yield create_response(
            "Creating backup ...",
            f=Format.PLEASE_WAIT
        )

        backup = await self.bot.core.backup_create(ctx.author.id, ctx.guild_id)

        backup_id = backup.id.upper()
        yield create_response(
            f"Successfully **created backup** with the id `{backup_id}`.\n\n"
            f"**Usage**\n"
            f"```/backup info backup_id: {backup_id}```"
            f"```/backup load backup_id: {backup_id}```\n"
            f"⭐ Use [Xenon Premium](https://wiki.xenon.bot/en/premium) to save messages, members, and bans!\n",
            f=Format.SUCCESS,
            update=True
        )

    async def _backup_load(self, ctx, backup_id, options, update=False):
        exists = await self.bot.core.backup_exists(ctx.author.id, backup_id.lower())
        if not exists:
            data = await self._unknown_backup_message(ctx.author.id, backup_id)
            yield InteractionResponse.message(**data)
            return

        parsed_options = parse_options(
            ("delete_roles", "delete_channels", "roles", "channels", "settings"),
            ALLOWED_OPTIONS,
            options
        )

        state_key = self.bot.state.insert({
            "backup_id": backup_id,
            "options": list(parsed_options)
        })

        data = create_warning_message(parsed_options, state_key)
        if update:
            yield InteractionResponse.update_message(**data)
        else:
            yield InteractionResponse.message(**data)

    @backup.sub_command(extends=dict(
        backup_id=dict(
            description="The id of the previously created backup"
        ),
        options="A list of options"
    ))
    @checks.guild_only
    def load(self, ctx, backup_id: str.strip, options: str.lower = ""):
        """
        Load a previously created backup on this server

        Get more help on the [wiki](https://wiki.xenon.bot/backups#loading-a-backup).
        """
        return self._backup_load(ctx, backup_id, options)

    @Module.component(name="backup_load_direct")
    def load_direct(self, ctx, backup_id):
        return self._backup_load(ctx, backup_id, "", update=True)

    @Module.component(name="backup_load_options")
    async def load_options(self, ctx, state_key):
        state = self.bot.state.pop(state_key)
        if state is None:
            yield create_response(
                "You were too slow, try again with `/backup load`",
                f=Format.ERROR,
                update=True
            )
            return

        state["options"] = []
        for option in ctx.values:
            if option in ALLOWED_OPTIONS:
                state["options"].append(option)
            else:
                yield create_response(
                    premium.PREMIUM_ONLY_TEXT.replace("command", "option"),
                    components=premium.PREMIUM_COMPONENTS,
                    embeds=[],
                    update=True
                )
                return

        state_key = self.bot.state.insert(state)
        yield InteractionResponse.update_message(**create_warning_message(state["options"], state_key))

    @Module.component(name="backup_load_cancel")
    async def load_cancel(self, ctx, state_key):
        self.bot.state.pop(state_key)
        yield create_response(
            "The loading process has been **cancelled**.\n\n"
            "Use `/backup load` to try again.",
            f=Format.INFO,
            update=True
        )

    @Module.component(name="backup_load_confirm")
    async def load_confirm(self, ctx, state_key):
        state = self.bot.state.pop(state_key)
        if state is None:
            yield create_response(
                "You were too slow, try again with `/backup load`",
                f=Format.ERROR,
                update=True
            )
            return

        yield create_response(
            "**The backup will start loading now**. Please be patient, this can take a while!\n\n"
            "Use `/backup status` to get the current status and `/backup cancel` to cancel the process.\n\n"
            "*This message might not be updated.*",
            f=Format.INFO,
            update=True
        )

        # TODO: core request

        try:
            yield create_response(
                f"Successfully **loaded the backup**.",
                f=Format.SUCCESS,
                update=True
            )
        except HTTPException:
            pass

    async def _backup_info_message(self, user_id, backup_id, direct_load=True):
        try:
            backup = await self.bot.core.backup_get(user_id, backup_id.lower())
        except NotFoundError:
            return await self._unknown_backup_message(user_id, backup_id)

        channel_list = channel_tree(backup.guild.channels)
        if len(channel_list) > 1024:
            channel_list = channel_list[:1000] + "\n...\n```"

        role_list = "```{}```".format("\n".join(
            [r.name for r in sorted(backup.guild.roles, key=lambda r: r.position, reverse=True)]
        ))
        if len(role_list) > 1024:
            role_list = role_list[:1000] + "\n...\n```"

        properties = []
        if backup.interval:
            properties.append("⏲️Interval")

        if backup.large:
            properties.append("🐘Large")

        if backup.encrypted:
            properties.append("🔒Encrypted")

        buttons = [
            Button(
                style=ButtonStyle.DANGER,
                label="Delete this backup",
                custom_id="backup_delete_direct",
                args=[backup_id]
            )
        ]
        if direct_load:
            buttons.insert(0, Button(
                style=ButtonStyle.PRIMARY,
                label="Load this backup",
                custom_id="backup_load_direct",
                args=[backup_id]
            ))

        return dict(
            embeds=[{
                "title": f"Backup Info - *{backup.guild_name}*",
                "color": Format.INFO.color,
                "footer": {"text": "  ".join(properties)},
                "fields": [
                    {
                        "name": "Created At",
                        "value": f"<t:{int(backup.timestamp)}:R>",
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
            }],
            components=[ActionRow(*buttons)],
            ephemeral=True
        )

    async def _backup_info(self, ctx, backup_id):
        data = await self._backup_info_message(ctx.author.id, backup_id, direct_load=ctx.guild_id is not None)
        yield InteractionResponse.message(**data)

    @backup.sub_command(extends=dict(
        backup_id=dict(
            description="The id of the previously created backup"
        )
    ))
    def info(self, ctx, backup_id: str.strip):
        """
        Get information about a previously created backup
        """
        return self._backup_info(ctx, backup_id)

    @Module.component(name="backup_info_direct")
    def info_direct(self, ctx):
        backup_id = ctx.values[0]
        return self._backup_info(ctx, backup_id)

    async def _backup_list_message(self, user_id, page):
        page = max(page, 1)

        data = await self.bot.core.backup_list(user_id, limit=10, skip=(page - 1) * 10)
        if data.total == 0:
            return dict(
                **create_message(
                    "You **don't have any backups** yet. Use `/backup create` to create one.",
                    f=Format.INFO
                ),
                ephemeral=True
            )

        fields = []
        select_options = []
        for backup in data.backups:
            properties = []
            if backup.interval:
                properties.append("⏲️")

            if backup.encrypted:
                properties.append("🔒")

            if backup.large:
                properties.append("🐘")

            backup_id = backup.id.upper()
            fields.append(dict(
                name=backup_id + f" • {' '.join(properties)}" * (len(properties) > 0),
                value=f"{backup.guild_name} (<t:{int(backup.timestamp)}:R>)"
            ))

            timestamp = datetime_to_string(datetime.fromtimestamp(backup.timestamp))
            select_options.append(SelectMenuOption(
                label=backup_id,
                description=f"{backup.guild_name} ({timestamp} UTC)"[:50],
                value=backup_id
            ))

        description = f"Displaying **{(page - 1) * 10 + 1}** - **{min(page * 10, data.total)}** " \
                      f"of **{data.total}** total backups"
        if data.total > page * 10:
            description += f"\n\nType `/backup list page: {page + 1}` for the next page"

        return dict(
            embeds=[dict(
                title="Backup List",
                fields=fields,
                color=Format.INFO.color,
                description=f"{description}\n​",
            )],
            components=[
                ActionRow(
                    SelectMenu(
                        *select_options,
                        max_values=1,
                        min_values=1,
                        custom_id="backup_info_direct",
                        placeholder="Select a backup"
                    )
                ),
                ActionRow(
                    Button(label="Previous Page", custom_id=f"backup_list", args=[str(page - 1)],
                           disabled=page <= 1),
                    Button(label="Next Page", custom_id=f"backup_list", args=[str(page + 1)],
                           disabled=data.total <= page * 10)
                )
            ],
            ephemeral=True
        )

    @backup.sub_command(extends=dict(
        page="The page to display (default 1)",
        master_kay="The master key (only for encrypted backups)"
    ))
    async def list(self, ctx, page: int = 1):
        """
        Get a list of all your previously created backups
        """
        data = await self._backup_list_message(ctx.author.id, page)
        yield InteractionResponse.message(**data)

    @Module.component(name="backup_list")
    async def list_page(self, ctx, page):
        data = await self._backup_list_message(ctx.author.id, int(page))
        yield InteractionResponse.update_message(**data)

    @backup.sub_command(extends=dict(
        backup_id=dict(
            description="The id of the previously created backup"
        )
    ))
    async def delete(self, ctx, backup_id: str.strip):
        """
        Delete a previously created backup >THIS CAN NOT BE UNDONE<

        Get more help on the [wiki](https://wiki.xenon.bot/backups#deleting-a-backup).
        """
        exists = await self.bot.core.backup_exists(ctx.author.id, backup_id.lower())
        if not exists:
            data = await self._unknown_backup_message(ctx.author.id, backup_id)
            yield InteractionResponse.message(**data)
            return

        yield InteractionResponse.message(
            **create_message("Are you sure that you want to delete this backup? **This can not be undone**.",
                             f=Format.WARNING),
            components=[ActionRow(
                Button(label="Confirm", custom_id=f"backup_delete_confirm", args=[backup_id],
                       style=ButtonStyle.SUCCESS),
                Button(label="Cancel", custom_id=f"backup_delete_cancel",
                       style=ButtonStyle.DANGER),
            )],
            ephemeral=True
        )

    @Module.component(name="backup_delete_direct")
    async def delete_direct(self, ctx, backup_id):
        yield InteractionResponse.update_message(
            **create_message("Are you sure that you want to delete this backup? **This can not be undone**.",
                             f=Format.WARNING),
            components=[ActionRow(
                Button(label="Confirm", custom_id=f"backup_delete_confirm", args=[backup_id],
                       style=ButtonStyle.SUCCESS),
                Button(label="Cancel", custom_id=f"backup_delete_cancel",
                       style=ButtonStyle.DANGER),
            )],
            ephemeral=True
        )

    @Module.component(name="backup_delete_confirm")
    async def delete_confirm(self, ctx, backup_id):
        try:
            await self.bot.core.backup_delete(ctx.author.id, backup_id.lower())
        except NotFoundError:
            data = await self._unknown_backup_message(ctx.author.id, backup_id)
            yield InteractionResponse.update_message(**data)
        else:
            yield create_response(
                "Successfully **deleted backup**.",
                f=Format.SUCCESS
            )

    @Module.component(name="backup_delete_cancel")
    async def delete_cancel(self, ctx):
        yield create_response(
            "The backup has not been deleted.\n\n"
            "Use `/backup delete` to try again.",
            f=Format.INFO
        )

    @backup.sub_command()
    async def purge(self, ctx):
        """
        Delete all of your backups >THIS CAN NOT BE UNDONE<
        """
        await InteractionResponse.message(**create_message(
            f"Are you sure that you want to delete all of your backups?",
            f=Format.WARNING
        ), components=[ActionRow(
            Button(label="Confirm", style=ButtonStyle.SUCCESS, custom_id="backup_purge_confirm"),
            Button(label="Cancel", style=ButtonStyle.DANGER, custom_id="backup_purge_cancel")
        )], ephemeral=True)

    @Module.component(name="backup_purge_confirm")
    async def purge_confirm(self, ctx):
        await self.bot.core.backup_delete_all(ctx.author.id)
        yield create_response(
            f"Successfully deleted all of your backups.",
            f=Format.SUCCESS
        )

    @Module.component(name="backup_purge_cancel")
    async def purge_cancel(self, ctx):
        yield create_response(
            "Your backups have **not** been **deleted**.\n\n"
            "Use `/backup purge` to try again.",
            f=Format.INFO,
            update=True
        )

    @backup.sub_command_group()
    async def interval(self, ctx):
        """
        Manage your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """

    @interval.sub_command()
    @checks.guild_only
    async def show(self, ctx):
        """
        Show your current backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        try:
            interval = await self.bot.core.backup_interval_get(ctx.author.id, ctx.guild_id)
        except NotFoundError:
            yield create_response(
                "The **backup interval is** currently turned **off**.\n"
                "Turn it on with `/backup interval on 24h`.",
                f=Format.ERROR
            )
            return

        backups = []
        resp = await self.bot.core.backup_list(ctx.author.id, ctx.guild_id, interval=True)
        for backup in resp.backups:
            backup_id = backup.id.upper()
            backups.append(f"**{backup_id}** (<t:{int(backup.timestamp)}:R>)")

        yield InteractionResponse.message(embeds=[{
            "color": Format.INFO.color,
            "title": "Backup Interval",
            "description": "\n".join(backups) + "\n\nType `/backup list` to get a detailed list of backups.\n​",
            "fields": [
                {
                    "name": "Interval",
                    "value": timedelta_to_string(timedelta(hours=interval.interval_hours)),
                    "inline": True
                },
                {
                    "name": "Last Backup",
                    "value": f"<t:{int(interval.last_backup)}:R>",
                    "inline": False
                },
                {
                    "name": "Next Backup",
                    "value": f"<t:{int(interval.next_backup)}:R>",
                    "inline": False
                }
            ]
        }], ephemeral=True)

    @interval.sub_command(
        extends=dict(
            interval=dict(
                description="The interval in which the backups are created (e.g. every 24 hours)",
                choices=(
                        ("⭐ 4 hours", "4h"),
                        ("⭐ 8 hours", "8h"),
                        ("⭐ 12 hours", "12h"),
                        ("24 hours", "24h"),
                        ("2 days", "2d"),
                        ("3 days", "3d"),
                        ("7 days", "7d"),
                        ("14 days", "14d"),
                        ("30 days", "30d")
                )
            )
        )
    )
    @checks.guild_only
    async def on(self, ctx, interval):
        """
        Enable your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        try:
            interval_td = string_to_timedelta(interval)
        except OverflowError:
            interval_td = timedelta(hours=24)

        hours = interval_td.total_seconds() // 3600

        interval = await self.bot.core.backup_interval_enable(ctx.author.id, ctx.guild_id, interval_hours=hours)
        yield create_response(
            "Successful **enabled the backup interval**.\nThe first backup will be created in "
            f"<t:{int(interval.next_backup)}:R>.\n\n"
            f"Type `/backup list` to view your interval backups.",
            f=Format.SUCCESS
        )

    @interval.sub_command()
    @checks.guild_only
    async def off(self, ctx):
        """
        Disable your backup interval for this server

        Get more help on the [wiki](https://wiki.xenon.bot/en/backups#automated-backups-interval).
        """
        try:
            await self.bot.core.backup_interval_disable(ctx.author.id, ctx.guild_id)
        except NotFoundError:
            yield create_response(
                f"Your backup interval is not enabled for this server.",
                f=Format.ERROR
            )
        else:
            yield create_response(
                "Successfully **disabled your backup interval** for this server.",
                f=Format.SUCCESS
            )
