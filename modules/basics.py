from dbots.cmd import *
import asyncio

FAQ = {
    "How do I invite Xenon to my server?":
        "Please click [here](<https://xenon.bot/invite>) to invite Xenon to your server.",
    "Is Xenon safe to use?":
        "",
    "I received an error, what do I do?":
        "Please read the error carefully and try to understand it. "
        "If you can't make sense of the error please join our [support server](https://xenon.bot/discord) "
        "and ask in the support channel.",
    "How do I load or create a backup?":
        "You can create a backup of your server using the `/backup create` command. "
        "You can find a list of your previously created backup using the `/backup list` command. "
        "Use the `/backup load` command to load a backup on any server.",
    "How do I load or create a template?":
        "You can find a list of templates and instructions on how to load them at https://templates.xenon.bot . "
        "If you want to create your own template please follow the instructions "
        "[here](<https://wiki.xenon.bot/templates#creating-a-template>).",
    "Where can I get Xenon Premium?":
        "You can find more information about Xenon Premium [here](<https://wiki.xenon.bot/en/premium>)"
        " and buy it [here](<https://www.patreon.com/merlinfuchs>).",
    "I bought Xenon Premium but I'm not able to use it?!":
        "Please join our [support server](<https://xenon.bot/discord>) and go to "
        "<https://www.patreon.com/settings/apps> to connect your discord account to patreon. "
        "You should see a channel called `#patrons-info` with instructions on how to activate premium. "
        "If you still can't see the channel try to disconnect and reconnect your discord on patreon."
}


class BasicsModule(Module):
    @Module.command()
    @guild_only
    @checks.is_guild_owner
    async def leave(self, ctx):
        """
        Make the bot leave this server
        """
        await ctx.respond(
            "Are you sure that you want Xenon to leave? :(",
            components=[ActionRow(
                Button(label="Nah, please stay!", style=ButtonStyle.SUCCESS, custom_id="leave_cancel"),
                Button(label="Yes, please leave!", style=ButtonStyle.DANGER, custom_id="leave_confirm"),
            )],
            ephemeral=True
        )

    @Module.component()
    async def leave_confirm(self, ctx):
        await ctx.update("Bye :(")
        await ctx.bot.http.leave_guild(ctx.guild_id)

    @Module.component()
    async def leave_cancel(self, ctx):
        await ctx.update("Cool, I will stay! :)")

    async def _faq_question_autocomplete(self, ctx, question):
        matching = [
            (q, q)
            for q in FAQ
            if question.strip() in q or q in question
        ]

        if len(matching) == 0:
            matching.append(("As your question on our support server.", question))

        return InteractionResponse.autocomplete(*matching[:25])

    @Module.command(extends=dict(
        question=dict(
            description="Your question",
            autocomplete=_faq_question_autocomplete
        )
    ))
    async def faq(self, ctx, question):
        """
        You need help? Find the answer to your question here!
        """
        try:
            answer = FAQ[question]
        except KeyError:
            answer = "Please join our [support server](<https://xenon.bot/discord>) and ask " \
                     "your question in the support channel."

        await ctx.respond(
            f"**{question}**\n\n{answer}\n\n*This didn't answer your question? Join our [support server](<https://xenon.bot/discord>).*",
            ephemeral=True
        )

    def _flattened_command_list(self):
        for cmd in self.bot.commands:
            if len(cmd.sub_commands) == 0:
                yield cmd.name, cmd
            else:
                for sub_cmd in cmd.sub_commands:
                    if isinstance(sub_cmd, SubCommand) or len(sub_cmd.sub_commands) == 0:
                        yield f"{cmd.name} {sub_cmd.name}", sub_cmd
                    else:
                        for sub_sub_cmd in sub_cmd.sub_commands:
                            yield f"{cmd.name} {sub_cmd.name} {sub_sub_cmd.name}", sub_sub_cmd

    async def _help_command_autocomplete(self, ctx, command):
        matched = [
            (name, name)
            for name, _ in self._flattened_command_list()
            if command.strip() in name
        ]

        return InteractionResponse.autocomplete(*matched[:25])

    @Module.command(
        extends=dict(
            command=dict(
                description="The full name of the command",
                autocomplete=_help_command_autocomplete
            )
        )
    )
    async def help(self, ctx, command=None):
        """
        Get a list of commands or more information about a specific command
        """
        for name, cmd in self._flattened_command_list():
            if name == command:
                break
        else:
            cmd = None

        if cmd is None:
            await ctx.respond(
                "**Xenon Help**\n\n"
                "__Useful Commands__\n"
                "`/backup create` - Create a backup\n"
                "`/backup load` - Load a previously created backup\n"
                "`/backup list` - List all your backups\n"
                "`/backup interval` - Manage automated backups\n"
                "`/template load` - Load a template from [templates.xenon.bot](<https://templates.xenon.bot>)\n\n"
                "Please visit our wiki or join our support discord if you need further help.\n​",
                components=[ActionRow(
                    Button(label="Wiki", url="https://wiki.xenon.bot", emoji="📚"),
                    Button(label="Support", url=await ctx.bot.get_support_invite(), emoji="❔"),
                    Button(label="Templates", url="https://templates.xenon.bot", emoji="🖼️"),
                    Button(label="Twitter", url="https://twitter.com/xenon_bot", emoji="🐦"),
                    Button(label="Premium", url="https://xenon.bot/patreon", emoji="⭐")
                )],
                ephemeral=True
            )
            return

        else:
            arg_list = "\n".join([f"**{option.name}**: *{option.description}*" for option in cmd.options])
            await ctx.respond(
                f"**/{cmd.full_name}**\n\n"
                f"{cmd.long_description}\n\n"
                f"{'**__Arguments__**' if len(arg_list) > 0 else ''}\n\n"
                f"{arg_list}",
                ephemeral=True
            )

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
            f"Click [here](<{await ctx.bot.get_invite()}>) to **invite Xenon** to your server.",
            components=[ActionRow(
                Button(label="Invite Xenon", url=await ctx.bot.get_invite()),
            )],
            ephemeral=True
        )

    @Module.command()
    async def support(self, ctx):
        """
        Join the support server and get some help
        """
        await ctx.respond(
            f"Click [here](<{await ctx.bot.get_support_invite()}>) to join the support server.",
            components=[ActionRow(
                Button(label="Support Server", url=await ctx.bot.get_support_invite()),
            )],
            ephemeral=True
        )

    @Module.command()
    async def vote(self, ctx):
        """
        Support Xenon by voting for it
        """
        await ctx.respond(
            f"Voting is free and helps us to reach more people. You can vote every 12 hours.\n"
            f"Click [here](<https://top.gg/bot/416358583220043796/vote>) to vote for Xenon.",
            components=[ActionRow(
                Button(label="Vote on top.gg", url="https://top.gg/bot/416358583220043796/vote"),
            )],
            ephemeral=True
        )
