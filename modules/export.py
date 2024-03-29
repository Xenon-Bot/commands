from dbots.cmd import *
from dbots import rest, ChannelType
from io import StringIO
import json
import csv
import re

from .premium import PREMIUM_ONLY_TEXT, PREMIUM_COMPONENTS


def _data_to_fp(data, _format):
    if _format == "json":
        fp = StringIO()
        json.dump(data, fp, indent=4)
        return fp

    if _format == "csv":
        fp = StringIO()
        fieldnames = [k for d in data for k in d.keys()]
        writer = csv.DictWriter(fp, fieldnames=set(fieldnames), delimiter=";")
        writer.writeheader()
        writer.writerows(data)
        return fp

    raise ValueError


FORMAT_ARG_EXTENDS = dict(
    description="The format of the exported file",
    choices=(
        ("JSON file", "json"),
        ("CSV file", "csv")
    )
)


def _parse_message_id(channel_id, message):
    regex = r"https:\/\/([a-z]+\.)?discord(app)?.com\/channels\/[0-9]+\/([0-9]+)\/([0-9]+)\/?"
    match = re.match(regex, message)
    if match:
        return match.group(3), match.group(4)

    return channel_id, message


class ExportModule(Module):
    @Module.command(dm_permission=False)
    async def export(self):
        """
        Export data from discord to JSON or other formats
        """

    @export.sub_command(extends=dict(
        format=FORMAT_ARG_EXTENDS
    ))
    @has_permissions_level()
    @checks.cooldown(1, 15, bucket=checks.CooldownType.AUTHOR)
    async def channels(self, ctx, format):
        """
        Export all channels as JSON or CSV
        """
        channels = await ctx.fetch_guild_channels()

        data = [c.to_dict() for c in channels]

        file_name = f"channels_{ctx.guild_id}"
        await ctx.respond(files=[rest.File(
            _data_to_fp(data, _format=format),
            filename=f"{file_name}.{format}"
        )], ephemeral=True)

    @export.sub_command(extends=dict(
        channel="The channel that you want to export"
    ))
    @has_permissions_level()
    @checks.cooldown(3, 15, bucket=checks.CooldownType.AUTHOR)
    async def channel(self, ctx, channel: CommandOptionType.CHANNEL):
        """
        Export a channel or category as JSON or CSV
        """
        channel = ctx.resolved.channels[channel]

        data = channel.to_dict()
        if channel.type == ChannelType.GUILD_CATEGORY:
            data["children"] = [
                c.to_dict()
                for c in await ctx.fetch_guild_channels()
                if c.parent_id == channel.id
            ]

        file_name = f"{channel.name.replace(' ', '_').lower()}_{channel.id}"
        await ctx.respond(files=[rest.File(
            _data_to_fp(data, _format="json"),
            filename=f"{file_name}.json"
        )], ephemeral=True)

    @export.sub_command(extends=dict(
        format=FORMAT_ARG_EXTENDS
    ))
    @has_permissions_level()
    @checks.cooldown(1, 15, bucket=checks.CooldownType.AUTHOR)
    async def roles(self, ctx, format):
        """
        Export all roles as JSON or CSV
        """
        roles = await ctx.fetch_guild_roles()

        data = [r.to_dict() for r in roles]

        file_name = f"roles_{ctx.guild_id}"
        await ctx.respond(files=[rest.File(
            _data_to_fp(data, _format=format),
            filename=f"{file_name}.{format}"
        )], ephemeral=True)

    @export.sub_command(extends=dict(
        role="The role that you want to export"
    ))
    @has_permissions_level()
    @checks.cooldown(5, 15, bucket=checks.CooldownType.AUTHOR)
    async def role(self, ctx, role: CommandOptionType.ROLE):
        """
        Export a role as JSON
        """
        role = ctx.resolved.roles[role]

        data = role.to_dict()
        file_name = f"{role.name.replace(' ', '_').lower()}_{role.id}"
        await ctx.respond(files=[rest.File(
            _data_to_fp(data, _format="json"),
            filename=f"{file_name}.json"
        )], ephemeral=True)

    @export.sub_command(extends=dict(
        format=FORMAT_ARG_EXTENDS
    ))
    @has_permissions_level()
    @bot_has_permissions(ban_members=True)
    @checks.cooldown(1, 30, bucket=checks.CooldownType.AUTHOR)
    async def bans(self, ctx, format):
        """
        Export all bans as JSON or CSV
        """
        await ctx.respond(PREMIUM_ONLY_TEXT, components=PREMIUM_COMPONENTS, ephemeral=True)
        return

    @export.sub_command(extends=dict(
        message="The id or url of the message that you want to export"
    ))
    @has_permissions(manage_messages=True)
    @bot_has_permissions(read_message_history=True)
    @checks.cooldown(3, 15, bucket=checks.CooldownType.AUTHOR)
    async def message(self, ctx, message):
        """
        Export a message as JSON
        """
        await ctx.respond(PREMIUM_ONLY_TEXT, components=PREMIUM_COMPONENTS, ephemeral=True)
        return

    @export.sub_command(extends=dict(
        message="The id or url of the message that you want to export",
        format=FORMAT_ARG_EXTENDS
    ))
    @has_permissions(manage_messages=True)
    @bot_has_permissions(read_message_history=True, manage_messages=True)
    @checks.cooldown(1, 30, bucket=checks.CooldownType.AUTHOR, manual=True)
    async def reactions(self, ctx, message, format):
        """
        Export the reactions from a message as JSON or CSV
        """
        await ctx.respond(PREMIUM_ONLY_TEXT, components=PREMIUM_COMPONENTS, ephemeral=True)
        return
