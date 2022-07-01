from dbots.cmd import *
from dbots import *
import inspect
import textwrap
import traceback
import json
from datetime import datetime


class AdminModule(Module):
    @Module.command(default_member_permissions=0)
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

    @Module.command(default_member_permissions=0)
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

    @Module.command(default_member_permissions=0)
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

    @Module.command(default_member_permissions=0)
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

    @Module.command(default_member_permissions=0)
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

    @Module.command(default_member_permissions=0)
    @checks.is_bot_owner
    async def blacklist(self, ctx):
        """
        Manage the blacklist
        """

    @blacklist.sub_command_group(name="add")
    @checks.is_bot_owner
    async def blacklist_add(self, ctx):
        """
        Add a user or server to the blacklist
        """

    @blacklist_add.sub_command(name="user")
    @checks.is_bot_owner
    async def blacklist_add_user(self, ctx, user: CommandOptionType.USER, reason):
        """
        Add a user to the blacklist
        """
        await ctx.bot.db.blacklist.replace_one({"_id": user}, {
            "_id": user,
            "guild": False,
            "timestamp": datetime.utcnow(),
            "staff": ctx.author.id,
            "reason": reason
        }, upsert=True)
        await ctx.respond(**create_message(
            f"Successfully **added <@{user}> to the blacklist**.",
            f=Format.SUCCESS
        ), ephemeral=True)

    @blacklist_add.sub_command(name="server")
    @checks.is_bot_owner
    async def blacklist_add_guild(self, ctx, server_id, reason):
        """
        Add a server to the blacklist
        """
        await ctx.bot.db.blacklist.replace_one({"_id": server_id}, {
            "_id": server_id,
            "guild": True,
            "timestamp": datetime.utcnow(),
            "staff": ctx.author.id,
            "reason": reason
        }, upsert=True)
        await ctx.respond(**create_message(
            f"Successfully **added the server with the id `{server_id}` to the blacklist**.",
            f=Format.SUCCESS
        ), ephemeral=True)

    @blacklist.sub_command_group(name="remove")
    @checks.is_bot_owner
    async def blacklist_remove(self, ctx):
        """
        Remove a user or server from the blacklist
        """

    @blacklist_remove.sub_command(name="user")
    @checks.is_bot_owner
    async def blacklist_remove_user(self, ctx, user: CommandOptionType.USER):
        """
        Remove a user from the blacklist
        """
        await ctx.bot.db.blacklist.delete_one({"_id": user})
        await ctx.respond(**create_message(
            f"Successfully **removed <@{user}> from the blacklist**.",
            f=Format.SUCCESS
        ), ephemeral=True)

    @blacklist_remove.sub_command(name="server")
    @checks.is_bot_owner
    async def blacklist_remove_guild(self, ctx, server_id):
        """
        Remove a server from the blacklist
        """
        await ctx.bot.db.blacklist.delete_one({"_id": server_id, "guild": True})
        await ctx.respond(**create_message(
            f"Successfully **added the server with the id `{server_id}` to the blacklist**.",
            f=Format.SUCCESS
        ), ephemeral=True)

    @blacklist.sub_command_group(name="show")
    @checks.is_bot_owner
    async def blacklist_show(self, ctx):
        """
        Show a user or server from the blacklist
        """

    @blacklist_show.sub_command(name="user")
    @checks.is_bot_owner
    async def blacklist_show_user(self, ctx, user: CommandOptionType.USER):
        """
        Show a user from the blacklist
        """
        entry = await ctx.bot.db.blacklist.find_one({"_id": user})
        if entry is None:
            await ctx.respond(**create_message(
                "This user is not blacklisted.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        await ctx.respond(**create_message(
            f"The user <@{user}> has been blacklisted because of the following reason:"
            f"```{entry['reason']}```",
            f=Format.SUCCESS
        ), ephemeral=True)

    @blacklist_show.sub_command(name="server")
    @checks.is_bot_owner
    async def blacklist_show_guild(self, ctx, server_id):
        """
        Show a server from the blacklist
        """
        entry = await ctx.bot.db.blacklist.find_one({"_id": server_id, "guild": True})
        if entry is None:
            await ctx.respond(**create_message(
                "This server is not blacklisted.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        await ctx.respond(**create_message(
            f"The server with the id `{server_id}` has been blacklisted because of the following reason:"
            f"```{entry['reason']}```",
            f=Format.SUCCESS
        ), ephemeral=True)
