from dbots.cmd import *
import asyncio


class BasicsModule(Module):
    @Module.command()
    @guild_only
    @checks.is_guild_owner
    async def leave(self, ctx):
        """
        Make the bot leave this server
        """
        # Require a confirmation by the user
        await ctx.respond(
            "Are you sure that you want Xenon to leave? :(",
            components=[ActionRow(
                Button(label="Nah, please stay!", style=ButtonStyle.SUCCESS, custom_id="leave_cancel"),
                Button(label="Yes, please leave!", style=ButtonStyle.DANGER, custom_id="leave_confirm"),
            )],
            ephemeral=True
        )

    @Module.button(name="leave_confirm")
    async def leave_confirm(self, ctx):
        await ctx.update("Bye :(")
        await ctx.bot.http.leave_guild(ctx.guild_id)

    @Module.button(name="leave_cancel")
    async def leave_cancel(self, ctx):
        await ctx.update("Cool, I will stay! :)")

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
                "**Xenon Help**\n\n"
                "__Useful Commands__\n"
                "`/backup create` - Create a backup\n"
                "`/backup load` - Load a previously created backup\n"
                "`/backup list` - List all your backups\n"
                "`/backup interval` - Manage automated backups\n"
                "`/template load` - Load a template from [templates.xenon.bot](https://templates.xenon.bot)\n\n"
                "Please [visit our wiki](https://wiki.xenon.bot) or join our "
                "[supper discord](https://xenon.bot/wiki) if you need further help.\n\n"
                "__Links__\n"
                "[Wiki](https://wiki.xenon.bot) • [Templates](https://templates.xenon.bot) • "
                "[Support](https://xenon.bot/discord) • [Twitter](https://twitter.com/xenon_bot)",
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
        await ctx.respond(
            f"Pong! <:stonks:763794050343370793>\n\n"
            f"Xenon is fully operational and is waiting for your commands.",
            ephemeral=True
        )

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
