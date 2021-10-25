from dbots.cmd import *

PERMISSION_DESCRIPTIONS = {
    checks.PermissionLevels.ADMIN_ONLY: "Server admins can create backups, enable the backup interval and "
                                        "load a template or backup",
    checks.PermissionLevels.DESTRUCTIVE_OWNER: "Server admins can create backups and enable the backup interval "
                                               "but only the server owner can load backups or templates",
    checks.PermissionLevels.OWNER_ONLY: "Only the server owner can use any of the relevant commands"
}


class SettingsModule(Module):
    @Module.command()
    async def settings(self, ctx):
        """
        Manage Xenon internal settings for this server
        """

    @settings.sub_command()
    @guild_only
    @has_permissions(administrator=True)
    @cooldown(2, 10, bucket=checks.CooldownType.GUILD)
    async def show(self, ctx):
        """
        Show the current settings for this server
        """
        settings = await ctx.bot.db.guilds.find_one({"_id": ctx.guild_id}) or {}
        permissions_level = PermissionLevels(
            settings.get("permissions_level", PermissionLevels.DESTRUCTIVE_OWNER.value)
        )

        await ctx.respond(embeds=[{
            "title": "Server Settings",
            "color": Format.INFO.color,
            "fields": [
                {
                    "name": f"Permissions Level: *{permissions_level.name.replace('_', ' ').title()}*",
                    "value": PERMISSION_DESCRIPTIONS[permissions_level]
                }
            ]
        }], ephemeral=True)

    @settings.sub_command()
    @guild_only
    @checks.is_guild_owner
    @checks.cooldown(1, 10, bucket=checks.CooldownType.GUILD)
    async def reset(self, ctx):
        """
        Reset the settings for this server to the default values
        """
        await ctx.bot.db.guilds.delete_one({"_id": ctx.guild_id})
        await ctx.respond(**create_message(
            "Successfully **reset settings** to the default values.",
            f=Format.SUCCESS
        ), ephemeral=True)

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
    @guild_only
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
        await ctx.respond(**create_message(
            "__Changed the permissions level for this server to:__\n\n"
            f"**{PERMISSION_DESCRIPTIONS[level]}**.\n\n"
            f"*Use `/help settings permissions` to get more info.*",
            f=Format.SUCCESS
        ), ephemeral=True)

    @Module.command()
    async def opt(self, ctx):
        """
        Opt in and out of end-user-data collection
        """

    @opt.sub_command(name="out")
    async def opt_out(self, ctx):
        """
        Opt out of end-user-data collection for your discord account
        """
        await ctx.respond(
            **create_message(
                "**Are you sure that you want to opt out of the collection and processing of your end-user-data?**\n\n"
                "Your messages, username, discriminator, and avatar will no "
                "longer be included in future backups and chatlogs. "
                "Your messages will no longer be synced across channels.",
                f=Format.WARNING
            ),
            components=[ActionRow(
                Button(label="Nah, I changed my mind!", style=ButtonStyle.SUCCESS, custom_id="opt_out_cancel"),
                Button(label="Yes!", style=ButtonStyle.DANGER, custom_id="opt_out_confirm"),
            )],
            ephemeral=True
        )

    @Module.component()
    async def opt_out_confirm(self, ctx):
        # Force user into the database
        resp = await ctx.bot.session.get(f"https://xenon.bot/api/v1/users/{ctx.author.id}")
        if resp.status != 200:
            await ctx.update(**create_message(
                "Failed to opt out, please contact a staff member.",
                f=Format.ERROR
            ))

        await ctx.bot.db.users.update_one({"_id": ctx.author.id}, {"$set": {"privacy_opt_out": True}})
        await ctx.update(**create_message(
            "Okay, your have **opted out** and we will no longer collect or process your end-user-data.",
            f=Format.SUCCESS
        ))

    @Module.component()
    async def opt_out_cancel(self, ctx):
        await ctx.update(**create_message(
            "Okay, you have **not opted out**!",
            f=Format.INFO
        ))

    @opt.sub_command(name="in")
    async def opt_in(self, ctx):
        """
        Opt in to end-user-data collection for your discord account (if you have previously opted out)
        """
        await ctx.bot.db.users.update_one({"_id": ctx.author.id}, {"$set": {"privacy_opt_out": False}})
        await ctx.respond(**create_message(
            "Okay, your have **opted in** and we may collect and process your end-user-data again.",
            f=Format.SUCCESS
        ))
