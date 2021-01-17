import dc_interactions as dc
from xenon.cmd import *

PERMISSION_DESCRIPTIONS = {
    checks.PermissionLevels.ADMIN_ONLY: "Server admins can create backups, enable the backup interval and "
                                        "load a template or backup",
    checks.PermissionLevels.DESTRUCTIVE_OWNER: "Server admins can create backups and enable the backup interval "
                                               "but only the server owner can load backups or templates",
    checks.PermissionLevels.OWNER_ONLY: "Only the server owner can use any of the relevant commands"
}


class SettingsModule(dc.Module):
    @dc.Module.command()
    async def settings(self, ctx):
        """
        Manage Xenon internal settings for this server
        """

    @settings.sub_command()
    @checks.cooldown(2, 10, bucket=checks.CooldownType.GUILD)
    async def show(self, ctx):
        """
        Show the current settings for this server
        """
        settings = await ctx.bot.db.guilds.find_one({"_id": ctx.guild_id}) or {}
        permissions_level = settings.get("permissions_level", PermissionLevels.DESTRUCTIVE_OWNER)

        await ctx.respond_with_source(embeds=[{
            "title": "Server Settings",
            "color": Format.INFO.color,
            "fields": [
                {
                    "name": "Permissions Level",
                    "value": PERMISSION_DESCRIPTIONS[permissions_level]
                }
            ]
        }])

    @settings.sub_command()
    @checks.is_guild_owner
    @checks.cooldown(1, 10, bucket=checks.CooldownType.GUILD)
    async def reset(self, ctx):
        """
        Reset the settings for this server to the default values
        """
        await ctx.bot.db.guilds.delete_one({"_id": ctx.guild_id})
        await ctx.respond_with_source(**create_message(
            "Successfully **reset settings** to the default values.",
            f=Format.SUCCESS
        ))

    @settings.sub_command(
        extends=dict(
            level=dict(
                description="The new permissions mode for this server",
                choices=(
                        ("Only the owner can use the relevant commands", "OWNER_ONLY"),
                        ("Admins can not take destructive actions", "DESTRUCTIVE_OWNER"),
                        ("Admins can use all commands", "ADMIN_ONLY")
                )
            )
        ),
        long_description=f"Set the permissions level for your server\n\n"
                         f"Get more help on the [wiki](https://wiki.xenon.bot/en/settings#permissions-settings).\n\n"
                         f"This affects the following commands:\n"
                         f"`backup load`, `backup create`, `template load`, `backup interval`\n\n"
                         f"__Levels__\n\n"
                         f"{PERMISSION_DESCRIPTIONS[PermissionLevels.ADMIN_ONLY]}"
                         f"```/settings permissions admins```\n\n"
                         f"{PERMISSION_DESCRIPTIONS[PermissionLevels.DESTRUCTIVE_OWNER]}"
                         f"```/settings permissions destructive owner```\n\n"
                         f"{PERMISSION_DESCRIPTIONS[PermissionLevels.OWNER_ONLY]}"
                         f"```/settings permissions owner```"
    )
    @checks.is_guild_owner
    @checks.cooldown(1, 10, bucket=checks.CooldownType.GUILD)
    async def permissions(self, ctx, level):
        """
        Set the permissions mode for this server
        """
        try:
            level = getattr(PermissionLevels, level)
        except ValueError:
            return

        if level == PermissionLevels.OWNER_ONLY:
            await ctx.bot.db.intervals.delete_many({"guild": ctx.guild_id, "user": {"$ne": ctx.author.id}})

        await ctx.bot.db.guilds.update_one(
            {"_id": ctx.guild_id},
            {"$set": {"_id": ctx.guild_id, "permissions_level": level}},
            upsert=True
        )
        await ctx.respond_with_source(**create_message(
            "__Changed the permissions level for this server to:__\n\n"
            f"**{PERMISSION_DESCRIPTIONS[level]}**.\n\n"
            f"*Use `/help settings permissions` to get more info.*",
            f=Format.SUCCESS
        ))
