from os import environ as env
from dbots.cmd import *
from dbots import *
import inspect
import textwrap
import traceback
import json
from datetime import datetime

ADMIN_GUILD_ID = env.get("ADMIN_GUILD_ID", "496683369665658880")


class AdminModule(Module):
    # @Module.command()
    async def debug(self, ctx):
        """
        Manage the admin commands for a server
        """

    # @debug.sub_command()
    @guild_only
    @checks.is_bot_owner
    async def enable(self, ctx):
        """
        Register the debug commands on this server
        """
        await self.bot.http.replace_guild_commands(ctx.guild_id, [
            c.to_payload() for c in self.commands
            if not c.register
        ])
        await ctx.respond(**create_message(
            f"Admin commands are now available on the server with the id `{ctx.guild_id}`",
            f=Format.SUCCESS
        ), ephemeral=True)

    # @debug.sub_command()
    @guild_only
    @checks.is_bot_owner
    async def disable(self, ctx):
        """
        Unregister the debug commands on this server
        """
        await self.bot.http.replace_guild_commands(ctx.guild_id, [])
        await ctx.respond(**create_message(
            f"Admin commands are no longer available on the server with the id `{ctx.guild_id}`",
            f=Format.SUCCESS
        ), ephemeral=True)

    # @Module.command(visible=False)
    @checks.is_bot_owner
    async def maintenance(self, ctx):
        """
        Enable or disable the maintenance mode
        """
        current = await self.bot.redis.exists("cmd:maintenance")
        if current:
            await self.bot.redis.delete("cmd:maintenance")
            await ctx.respond(**create_message(
                "**Disabled maintenance** mode.",
                f=Format.SUCCESS
            ), ephemeral=True)

        else:
            await self.bot.redis.set("cmd:maintenance", "1")
            await ctx.respond(**create_message(
                "**Enabled maintenance** mode.",
                f=Format.SUCCESS
            ), ephemeral=True)

    # @Module.command(visible=False)
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
            await ctx.respond(**create_message(
                f"```py\n{tb[:1900]}```",
                title="Eval Error",
                f=Format.SUCCESS
            ), ephemeral=True)

        else:
            await ctx.respond(**create_message(
                f"```py\n{result}```",
                title="Eval Result",
                f=Format.SUCCESS
            ), ephemeral=True)

    # @Module.command(visible=False)
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
            await ctx.respond(**create_message(
                f"```py\n{tb[:1900]}```",
                title="Exec Error",
                f=Format.SUCCESS
            ), ephemeral=True)

        else:
            await ctx.respond(**create_message(
                f"```py\n{result}```",
                title="Exec Result",
                f=Format.SUCCESS
            ), ephemeral=True)

    # @Module.command(visible=False)
    @checks.is_bot_owner
    async def redis(self, ctx, cmd):
        """
        Execute a redis command
        """
        result = await ctx.bot.redis.execute(*cmd.split(" "))
        await ctx.respond(**create_message(
            f"```py\n{result}\n```",
            title="Redis Result",
            f=Format.SUCCESS
        ), ephemeral=True)

    @Module.command(visible=True)
    @checks.is_bot_owner
    async def error(self, ctx, error_id: str.lower = None, delete: bool = False):
        """
        Show information about a command error
        """
        if error_id is None:
            keys = []
            for key in await ctx.bot.redis.keys(f"cmd:errors:*"):
                key = key.decode("utf-8")
                keys.append((key.split(":")[-1].upper(), await ctx.bot.redis.pttl(key)))
                if delete:
                    await ctx.bot.redis.delete(key)

            error_list = ", ".join([f"`{key[0]}`" for key in sorted(keys, key=lambda k: k[1], reverse=True)])
            await ctx.respond(**create_message(
                error_list or "None in the last 24 hours",
                title="Command Errors",
                f=Format.INFO
            ), ephemeral=True)
            return

        elif error_id == "test":
            # Just to test if error is working correctly
            raise ValueError

        error = await ctx.bot.redis.get(f"cmd:errors:{error_id}")
        if error is None:
            await ctx.respond(**create_message(
                f"**Unknown error** with the id `{error_id.upper()}`.",
                f=Format.ERROR
            ), ephemeral=True)
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
                    "name": "Args",
                    "value": "\n".join([f"**{k}**: `{v}`" for k, v in data.get("args", {}).items()]) or "None",
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
            await ctx.respond(embeds=embeds[:3], ephemeral=True)
            embeds = embeds[3:]

        if delete:
            await ctx.bot.redis.delete(f"cmd:errors:{error_id}")

    # @Module.command(visible=False)
    @checks.is_bot_owner
    async def blacklist(self, ctx):
        """
        Manage the blacklist
        """
