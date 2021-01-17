import dc_interactions as dc
from os import environ as env
from xenon.cmd import *
import inspect
import textwrap
import traceback
import json
from datetime import datetime

ADMIN_GUILD_ID = env.get("ADMIN_GUILD_ID", "496683369665658880")


class AdminModule(dc.Module):
    @dc.Module.command(guild_id=ADMIN_GUILD_ID)
    async def admin(self, ctx):
        """
        Manage the admin commands for a server
        """

    @admin.sub_command()
    @checks.is_bot_owner
    async def enable(self, ctx, guild_id=None):
        """
        Add the admin commands to a server
        """
        guild_id = guild_id or ctx.guild_id
        await ctx.ack_with_source()

        for command in self.commands:
            if command.register:
                continue

            await self.bot.create_command(command, guild_id=guild_id)

        await ctx.respond_with_source(**create_message(
            f"Admin commands are now available on the server with the id `{guild_id}`",
            f=Format.SUCCESS
        ))

    @admin.sub_command()
    @checks.is_bot_owner
    async def disable(self, ctx, guild_id=None):
        """
        Remove the admin commands from a server
        """
        guild_id = guild_id or ctx.guild_id
        await ctx.ack_with_source()

        existing_commands = await ctx.bot.fetch_commands(guild_id=guild_id)
        for command in self.commands:
            if command.register:
                continue

            for ex_cmd in existing_commands:
                if ex_cmd["name"] == command.name:
                    await self.bot.delete_command(ex_cmd["id"], guild_id=guild_id)

        await ctx.respond_with_source(**create_message(
            f"Admin commands are no longer available on the server with the id `{guild_id}`",
            f=Format.SUCCESS
        ))

    @dc.Module.command(register=False)
    @checks.is_bot_owner
    async def maintenance(self, ctx):
        """
        Enable or disable the maintenance mode
        """
        current = await self.bot.redis.exists("cmd:maintenance")
        if current:
            await self.bot.redis.delete("cmd:maintenance")
            await ctx.respond_with_source(**create_message(
                "**Disabled maintenance** mode.",
                f=Format.SUCCESS
            ))

        else:
            await self.bot.redis.set("cmd:maintenance", "1")
            await ctx.respond_with_source(**create_message(
                "**Enabled maintenance** mode.",
                f=Format.SUCCESS
            ))

    @dc.Module.command(register=False)
    async def morph(self, ctx, user_id=None):
        """
        Morph into and execute commands as a different user
        """
        if user_id is None:
            morph_source = getattr(ctx.payload, "morph_source", None)
            if morph_source is None:
                await ctx.respond_with_source(**create_message(
                    "You are already executing commands as yourself.",
                    f=Format.SUCCESS
                ))
                return

            await ctx.bot.redis.delete(f"cmd:morph:{morph_source}")
            await ctx.respond_with_source(**create_message(
                "You are now executing commands as yourself.",
                f=Format.SUCCESS
            ))
            return

        check_result = await checks.is_bot_owner.run(ctx)
        if check_result is not True:
            return

        await ctx.bot.redis.set(f"cmd:morph:{ctx.author.id}", user_id)
        await ctx.respond_with_source(**create_message(
            f"You are now executing commands as <@{user_id}>.",
            f=Format.SUCCESS
        ))

    @dc.Module.command(register=False)
    @checks.is_bot_owner
    async def eval(self, ctx, expression):
        """
        Evaluate a python expression
        """
        if expression.startswith("await "):
            expression = expression[6:]

        try:
            result = eval(expression)
            if inspect.isawaitable(result):
                result = await result

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            await ctx.respond_with_source(**create_message(
                f"```py\n{tb[:1900]}```",
                title="Eval Error",
                f=Format.SUCCESS
            ))

        else:
            await ctx.respond_with_source(**create_message(
                f"```py\n{result}```",
                title="Eval Result",
                f=Format.SUCCESS
            ))

    @dc.Module.command(register=False)
    @checks.is_bot_owner
    async def exec(self, ctx, snippet):
        """
        Execute a python code snippet
        """
        if snippet.startswith('```') and snippet.endswith('```'):
            snippet = '\n'.join(snippet.split('\n')[1:-1])

        snippet = snippet.strip("` \n")
        wrapped = f"async def func():\n{textwrap.indent(snippet, '    ')}"

        env = {
            "ctx": ctx,
            "self": self,
            "bot": ctx.bot,
            "http": ctx.bot.http,
            "redis": ctx.bot.redis
        }

        try:
            exec(wrapped, env)
            result = await env["func"]()

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            await ctx.respond_with_source(**create_message(
                f"```py\n{tb[:1900]}```",
                title="Exec Error",
                f=Format.SUCCESS
            ))

        else:
            await ctx.respond_with_source(**create_message(
                f"```py\n{result}```",
                title="Exec Result",
                f=Format.SUCCESS
            ))

    @dc.Module.command(register=False)
    @checks.is_bot_owner
    async def redis(self, ctx, cmd):
        """
        Execute a redis command
        """
        result = await ctx.bot.redis.execute(*cmd.split(" "))
        await ctx.respond_with_source(**create_message(
            f"```py\n{result}\n```",
            title="Redis Result",
            f=Format.SUCCESS
        ))

    @dc.Module.command(register=False)
    @checks.is_bot_owner
    async def error(self, ctx, error_id: str.lower):
        """
        Show information about a command error
        """
        error = await ctx.bot.redis.get(f"cmd:errors:{error_id}")
        if error is None:
            await ctx.respond_with_source(**create_message(
                f"**Unknown error** with the id `{error_id.upper()}`.",
                f=Format.ERROR
            ))
            return

        data = json.loads(error)
        embeds = [{
            "title": "Command Error",
            "color": Format.ERROR.color,
            "fields": [
                {
                    "name": "Command",
                    "value": data["command"],
                    "inline": True
                },
                {
                    "name": "Author",
                    "value": f"<@{data['author']}>",
                    "inline": True
                },
                {
                    "name": "Timestamp",
                    "value": datetime_to_string(datetime.fromtimestamp(data["timestamp"])) + " UTC",
                    "inline": True
                }
            ]
        }]

        current = ""
        for line in data["traceback"].splitlines():
            if (len(current) + len(line)) > 2000:
                embeds.append({
                    "color": Format.ERROR.color,
                    "description": f"```py\n{current}```"
                })
                current = ""

            else:
                current += f"\n{line}"

        if len(current) > 0:
            embeds.append({
                "color": Format.ERROR.color,
                "description": f"```py\n{current}```"
            })

        while len(embeds) > 0:
            await ctx.respond_with_source(embeds=embeds[:3])
            embeds = embeds[3:]

    @dc.Module.command(register=False)
    @checks.is_bot_owner
    async def blacklist(self, ctx):
        """
        Manage the blacklist
        """
