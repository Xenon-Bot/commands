from dbots.cmd import *
from dbots import *
import asyncio
import traceback


class CloneModule(Module):
    @Module.command()
    async def clone(self, ctx):
        """
        Create a clone of a channel or role
        """

    @clone.sub_command(
        extends=dict(
            role="The channel to clone",
            apply_overwrites="Wether to also clone all child channels (only applies if the channel is a category)"
        )
    )
    @guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("manage_channels")
    @checks.not_in_maintenance
    @checks.cooldown(2, 30, bucket=checks.CooldownType.GUILD, manual=True)
    async def channel(self, ctx, channel: CommandOptionType.CHANNEL, child_channels: bool = False):
        """
        Create a clone of channel including permission overwrites
        """
        channels = await ctx.fetch_guild_channels()
        channel = iterable_get(channels, id=channel)

        if channel is None:
            # Shouldn't be reachable unless the command was manipulated
            await ctx.respond(**create_message(
                f"Can't find the specified channel in this server",
                f=Format.ERROR
            ))
            return

        children = []
        if child_channels:
            for child in channels:
                if child.parent_id == channel.id:
                    children.append(child)

        if len(channels) + len(children) >= 500:
            await ctx.respond(**create_message(
                "There is **not enough space** to clone the channel(s). Each server can only have up to 500 channels.",
                f=Format.ERROR
            ))

        await ctx.count_cooldown()
        new_channel = await ctx.bot.http.create_guild_channel(ctx.guild_id, **channel.to_dict())
        for child in sorted(children, key=lambda c: c.position):
            try:
                data = child.to_dict()
                data["parent_id"] = new_channel.id
                await ctx.bot.http.create_guild_channel(ctx.guild_id, **data)
            except rest.HTTPException:
                traceback.print_exc()
                continue

        if channel.type == ChannelType.GUILD_CATEGORY:
            if child_channels:
                await ctx.respond(**create_message(
                    f"Successfully **cloned the category** <#{new_channel.id}> including all child channels..",
                    f=Format.SUCCESS
                ))

            else:
                await ctx.respond(**create_message(
                    f"Successfully **cloned the category** <#{new_channel.id}>.",
                    f=Format.SUCCESS
                ))

        else:
            await ctx.respond(**create_message(
                f"Successfully **cloned the channel** <#{new_channel.id}>.",
                f=Format.SUCCESS
            ))

    @clone.sub_command(
        extends=dict(
            role="The role to clone",
            apply_overwrites="Wether to apply permission overwrites from the original role to the new one"
        )
    )
    @guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("manage_channels", "manage_roles")
    @checks.not_in_maintenance
    @checks.cooldown(3, 60, bucket=checks.CooldownType.GUILD, manual=True)
    async def role(self, ctx, role: CommandOptionType.ROLE, apply_overwrites: bool = False):
        """
        Create a clone of a role optionally including channel permission overwrites
        """
        roles = await ctx.fetch_guild_roles()
        role = iterable_get(roles, id=role)
        if role is None:
            # Shouldn't be reachable unless the command was manipulated
            await ctx.respond(**create_message(
                f"Can't find the specified role in this server",
                f=Format.ERROR
            ))
            return

        if len(roles) >= 250:
            await ctx.respond(**create_message(
                "There are already **250 roles in this server**. Delete one to be able to create a new one.",
                f=Format.ERROR
            ))

        new_role = await ctx.bot.http.create_guild_role(ctx.guild_id, **role.to_dict())
        if apply_overwrites:
            channels = await ctx.fetch_guild_channels()
            for channel in channels:
                apply = False
                overwrites = []
                for id, t, ov in channel.permission_overwrites:
                    allow, deny = ov.pair()
                    overwrites.append({
                        "id": id,
                        "type": t,
                        "allow": allow.value,
                        "deny": deny.value
                    })

                    if id == role.id:
                        apply = True
                        overwrites.append({
                            "id": new_role.id,
                            "type": t,
                            "allow": allow.value,
                            "deny": deny.value
                        })

                if apply:
                    await ctx.bot.http.edit_channel(channel, permission_overwrites=overwrites)

        await ctx.respond(**create_message(
            f"Successfully **cloned the role**: <@&{new_role.id}>.",
            f=Format.SUCCESS
        ))
