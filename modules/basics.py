from dbots.cmd import *


class BasicsModule(Module):
    @Module.command()
    @checks.has_permissions_level()
    async def leave(self, ctx):
        """
        Make the bot leave this server
        """
        await ctx.respond("Bye :(", ephemeral=True)
        await ctx.bot.http.leave_guild(ctx.guild_id)

    @Module.command(
        extends=dict(
            command=dict(
                description="The full name of the command"
            )
        )
    )
    async def help(self, ctx, command=None):
        """
        Get a list of commands or more information about a specific command
        """

        def find_command():
            parts = command.strip(" /").split(" ")
            for cmd in ctx.bot.commands:
                if parts[0] == cmd.name:
                    if len(parts) == 1:
                        return cmd

                    for sub_cmd in cmd.sub_commands:
                        if parts[1] == sub_cmd.name:
                            if len(parts) == 2 or not isinstance(sub_cmd, SubCommandGroup):
                                return sub_cmd

                            for sub_sub_cmd in sub_cmd.sub_commands:
                                if parts[2] == sub_sub_cmd.name:
                                    return sub_sub_cmd

            return None

        if command is None:
            await ctx.respond(
                "Use this command to get more information about a specific command.\n"
                "For example: `/help command: backup load`.\n\n"
                "If you need further help, please check out the [wiki](https://wiki.xenon.bot)"
                " and join the [support server](https://xenon.bot/discord).",
                ephemeral=True
            )
            return

        cmd = find_command()
        if cmd is not None:
            arg_list = "\n".join([f"**{option.name}**: *{option.description}*" for option in cmd.options])
            await ctx.respond(
                f"**/{cmd.full_name}**\n\n"
                f"{cmd.long_description}\n\n"
                f"{'**__Arguments__**' if len(arg_list) > 0 else ''}\n\n"
                f"{arg_list}",
                ephemeral=True
            )

        else:
            await ctx.respond(**create_message(
                f"Unknown command: `{command}`",
                embed=False,
                f=Format.ERROR
            ), ephemeral=True)

    @Module.command()
    async def ping(self, ctx):
        """
        Ping? Pong!
        """
        await ctx.respond(f"Pong! <:stonks:763794050343370793>", ephemeral=True)

    @Module.command()
    async def invite(self, ctx):
        """
        Invite Xenon to your server
        """
        await ctx.respond(
            f"Click [here](https://xenon.bot/invite) to **invite Xenon** to your server.",
            ephemeral=True
        )

    @Module.command()
    async def support(self, ctx):
        """
        Join the support server and get some help
        """
        await ctx.respond(
            f"Click [here](https://xenon.bot/discord) to join the support server.",
            ephemeral=True
        )

    @Module.command()
    async def premium(self, ctx):
        """
        Get information about Xenon Premium
        """
        await ctx.respond(
            "**Xenon Premium** is the **paid version** of Xenon.\n"
            "You can buy it on [patreon](https://www.patreon.com/merlinfuchs) "
            "and find a detailed list of perks [here](https://wiki.xenon.bot/premium)",
            ephemeral=True
        )
