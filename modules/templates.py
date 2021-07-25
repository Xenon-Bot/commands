from dbots import *
from dbots.cmd import *
import re
from datetime import timedelta, datetime
from grpclib.exceptions import GRPCError
from dbots.protos import backups_pb2
import grpclib
import json

from .audit_logs import AuditLogType
from .backups import option_status_list, convert_v1_to_v2, channel_tree, parse_options, create_warning_message

ALLOWED_OPTIONS = ("delete_roles", "delete_channels", "roles", "channels", "settings")


class TemplatesModule(Module):
    async def _get_template(self, identifier):
        template = await self.bot.mongo.dtpl.templates.find_one({
            "internal": True,
            "$or": [{"name": identifier}, {"_id": identifier}]
        })
        if template is not None:
            return template

        match = re.match(r"https?://discord.new/(\w+)/?", identifier)
        if match:
            identifier = match.group(1)

        cached = await self.bot.redis.get(f"template:{identifier}")
        if cached is not None:
            return json.loads(cached)

        try:
            data = await self.bot.http.get_template(identifier)
            guild = data["serialized_source_guild"]
            parsed = {
                "name": data["name"],
                "description": data["description"],
                "creator_id": data["creator_id"],
                "usage_count": data["usage_count"],
                "approved": True,
                "data": {
                    "id": data["source_guild_id"],
                    "name": data["name"],
                    "afk_channel_id": str(data["afk_channel_id"]) if data.get("afk_channel_id") else None,
                    "system_channel_id": str(data["system_channel_id"]) if data.get("system_channel_id") else None,
                    "system_channel_flags": data.get("system_channel_flags"),
                    "verification_level": data.get("verification_level"),
                    "afk_timeout": data.get("verification_level"),
                    "default_message_notifications": data.get("default_message_notifications"),
                    "explicit_content_filter": data.get("explicit_content_filter"),
                    "roles": [
                        {
                            "position": pos,
                            "id": str(r.pop("id")),
                            **r
                        }
                        for pos, r in enumerate(guild.pop("roles", []))
                    ],
                    "channels": [
                        {
                            "id": str(c.pop("id")),
                            "parent_id": str(c.pop("parent_id")) if c.get("parent_id") else None,
                            "permission_overwrites": [
                                {
                                    "id": str(ov.pop("id")),
                                    **ov
                                }
                                for ov in c.pop("permission_overwrites", [])
                            ],
                            **c
                        }
                        for c in guild.pop("channels", [])
                    ],
                }
            }
            await self.bot.redis.setex(f"template:{identifier}", 60 * 3, json.dumps(parsed))
            return parsed
        except rest.HTTPNotFound:
            return None

    @Module.command()
    async def template(self, ctx):
        """
        Choose from thousands of free server templates
        """

    @template.sub_command()
    async def create(self, ctx):
        """
        Create a new public template
        """
        await ctx.respond(
            "Please use [templates.xenon.bot](https://templates.xenon.bot) to add new templates, "
            "you can find help on the [wiki](https://wiki.xenon.bot/en/templates#creating-a-template) "
            "for how to create new templates.",
            ephemeral=True
        )

    @template.sub_command(extends=dict(
        name_or_id="The name, id or url of the template that you want to load",
        options="A list of options"
    ))
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    @checks.not_in_maintenance
    @checks.cooldown(1, 5 * 60, bucket=checks.CooldownType.GUILD, manual=True)
    async def load(self, ctx, name_or_id: str.strip, options: str.lower = ""):
        """
        Load one of the public templates

        You can find more help on the [wiki](https://wiki.xenon.bot/templates#loading-a-template).
        """
        template = await self._get_template(name_or_id)
        if template is None:
            await ctx.respond(**create_message(
                f"Can't find a template with the name, id or url `{name_or_id}`.\n"
                f"Go to [templates.xenon.bot](https://templates.xenon.bot) to get a list of available templates.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        parsed_options = parse_options(
            ("delete_roles", "delete_channels", "roles", "channels", "settings"),
            ALLOWED_OPTIONS,
            options
        )

        redis_key = f"template_load:{unique_id()}"
        await ctx.bot.redis.setex(redis_key, 60 * 5, json.dumps({
            "name_or_id": name_or_id,
            "options": list(parsed_options)
        }))

        await ctx.respond(**create_warning_message(parsed_options, redis_key, prefix="template_"), ephemeral=True)

    @Module.component(name="template_load_options")
    async def load_options(self, ctx, redis_key):
        scope = await ctx.bot.redis.get(redis_key)
        if scope is None:
            await ctx.update(**create_message(
                "You were too slow, try again with `/backup load`",
                f=Format.ERROR
            ))
            return

        scope = json.loads(scope)
        scope["options"] = [o for o in ctx.values if o in ALLOWED_OPTIONS]
        await ctx.bot.redis.setex(redis_key, 60 * 5, json.dumps(scope))
        await ctx.update(**create_warning_message(scope["options"], redis_key, prefix="template_"))

    @Module.component(name="template_load_cancel")
    async def load_cancel(self, ctx, redis_key):
        await ctx.bot.redis.delete(redis_key)
        await ctx.update(**create_message(
            "The loading process has been **cancelled**.\n\n"
            "Use `/template load` to try again.",
            f=Format.INFO
        ), ephemeral=True)

    @Module.component(name="template_load_confirm")
    async def load_confirm(self, ctx, redis_key):
        scope = await ctx.bot.redis.get(redis_key)
        if scope is None:
            return

        scope = json.loads(scope)
        name_or_id, options = scope["name_or_id"], scope["options"]

        template = await self._get_template(name_or_id)
        if template is None:
            await ctx.update(**create_message(
                f"Can't find a template with the name, id or url `{name_or_id}`.\n"
                f"Go to [templates.xenon.bot](https://templates.xenon.bot) to get a list of available templates.",
                f=Format.ERROR
            ))
            return

        data = convert_v1_to_v2(template["data"])

        role_route = rest.Route("POST", "/guilds/{guild_id}/roles", guild_id=ctx.guild_id)
        rl = await ctx.bot.http.get_bucket(role_route.bucket)
        if rl is not None and rl.remaining < len(data.roles) and "roles" in options:
            await ctx.update(**create_message(
                f"Due to a **Discord limitation** the bot is **not able to load this template** at the moment.\n\n"
                f"You have to wait **{timedelta_to_string(timedelta(seconds=rl.delta))}** "
                f"before you can load a template containing this many roles again.\n\n"
                f"You can also load this template without roles using"
                f"```/template load name_or_id: {name_or_id} options: !delete_roles !roles```",
                f=Format.ERROR
            ))
            return

        await self.load.cooldown.count(ctx)

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.TEMPLATE_LOAD,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

        ids = {}
        translator = await ctx.bot.db.id_translators.find_one({
            "target_id": ctx.guild_id,
            "source_id": data.id
        })
        if translator is not None:
            ids = translator.get("ids", {})

        await ctx.update(**create_message(
            "**The template is now loading**. Please be patient, this can take a while!\n\n"
            "Use `/template status` to get the current status and `/template cancel` to cancel the process.\n\n"
            "*This message might not be updated.*",
            f=Format.INFO
        ))

        try:
            replies = await self.bot.rpc.backups.Load(backups_pb2.LoadRequest(
                guild_id=ctx.guild_id,
                options=list(options),
                message_count=0,
                data=data,
                reason="Template loaded by " + str(ctx.author),
                ids=ids
            ))
        except GRPCError as e:
            if e.status == grpclib.Status.ALREADY_EXISTS:
                await ctx.update(**create_message(
                    f"There is **already a loading process running** on this server.\n"
                    f"Please wait for it to finish or use `/template cancel` to stop it.",
                    f=Format.ERROR
                ))
                return
            elif e.status == grpclib.Status.NOT_FOUND:
                await ctx.update(**create_message(
                    f"Xenon doesn't seem to be on this server, "
                    f"please click [here](https://xenon.bot/invite) to invite it again.",
                    f=Format.ERROR
                ))
                return
            elif e.status == grpclib.Status.RESOURCE_EXHAUSTED:
                await ctx.update(**create_message(
                    f"Xenon is currently experiencing increased load and can't process your request, "
                    f"please **try again in a few minutes**.",
                    f=Format.ERROR
                ))
                return
            elif e.status == grpclib.Status.OUT_OF_RANGE:
                await ctx.update(**create_message(
                    f"Due to a **Discord limitation** the bot is **not able to load this template** at the moment.\n\n"
                    f"You have to wait **{timedelta_to_string(timedelta(seconds=int(e.message)))}** "
                    f"before you can load a template containing this many roles again.\n\n"
                    f"You can also load this template without roles using"
                    f"```/template load name_or_id: {name_or_id} options: !delete_roles !roles```",
                    f=Format.ERROR
                ))
                return
            elif e.status == grpclib.Status.CANCELLED:
                return
            else:
                raise

        try:
            await ctx.update(**create_message(
                f"Successfully **loaded the template**.",
                f=Format.SUCCESS
            ))
        except rest.HTTPException:
            pass

        # Save ids for later use and recovery
        await ctx.bot.db.id_translators.update_one(
            {
                "target_id": ctx.guild_id,
                "source_id": data.id,
            },
            {
                "$set": {
                    "target_id": ctx.guild_id,
                    "source_id": data.id,
                    **{
                        f"ids.{s}": t
                        for s, t in replies[-1].ids.items()
                    }
                },
                "$addToSet": {
                    "loaders": ctx.author.id
                }
            },
            upsert=True
        )

    @template.sub_command()
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.cooldown(2, 30, bucket=checks.CooldownType.GUILD)
    async def cancel(self, ctx):
        """
        Cancel the currently running loading process on this server
        """
        try:
            await self.bot.rpc.backups.CancelLoad(backups_pb2.CancelLoadRequest(guild_id=ctx.guild_id))
        except GRPCError as e:
            if e.status == grpclib.Status.NOT_FOUND:
                await ctx.respond(**create_message(
                    "There is **no loading process running** on this server.",
                    f=Format.ERROR
                ), ephemeral=True)
                return
            else:
                raise

        await ctx.respond(**create_message(
            "Successfully **cancelled the currently running loading process** on this server.",
            f=Format.SUCCESS
        ), ephemeral=True)

    @template.sub_command()
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.cooldown(2, 10, bucket=checks.CooldownType.GUILD)
    async def status(self, ctx):
        """
        Get the status of the currently running loading process
        """
        try:
            reply = await self.bot.rpc.backups.LoadStatus(backups_pb2.LoadStatusRequest(guild_id=ctx.guild_id))
        except GRPCError as e:
            if e.status == grpclib.Status.NOT_FOUND:
                await ctx.respond(**create_message(
                    "There is **no loading process running** on this server.",
                    f=Format.ERROR
                ), ephemeral=True)
                return
            else:
                raise

        estimated_time_left = sum([
            o.estimated_time_left
            for o in reply.options.values()
            if o.state != backups_pb2.LoadStatus.State.WAITING
        ])

        minutes = estimated_time_left // 60
        seconds = estimated_time_left % 60
        if minutes == 0:
            etl = "< 1 minute"
        else:
            etl = timedelta_to_string(timedelta(minutes=minutes + int(seconds > 0)))

        details = "\n\n" + "\n".join([f"```{o.details}```" for o in reply.options.values() if o.details])
        for o in reply.options.values():
            if o.state == backups_pb2.LoadStatus.State.RATE_LIMIT:
                details += f"\n```A long lasting ratelimit has been hit, " \
                           f"you might want to cancel the loading process.```"
                break

        await ctx.respond(**create_message(
            f"Estimated time required for this step: `{etl}`\n\n"
            f"Type `/template cancel` to cancel the loading process.\n\n"
            f"{option_status_list(reply.options)}"
            f"{details}",
            title="Loading Status",
            f=Format.INFO
        ), ephemeral=True)

    @template.sub_command()
    async def list(self, ctx):
        """
        Get a list of available public templates
        """
        await ctx.respond(
            "Go to [templates.xenon.bot](https://templates.xenon.bot) to get a list of available template.\n"
            "You can also search by name and category to find the best template for you.",
            ephemeral=True
        )

    @template.sub_command(extends=dict(
        name_or_id="The name, id or url of the template that you want to load"
    ))
    @checks.cooldown(2, 10, bucket=checks.CooldownType.AUTHOR)
    async def info(self, ctx, name_or_id: str.strip):
        """
        Get information about a public template
        """
        template = await self._get_template(name_or_id)
        if template is None:
            await ctx.respond(**create_message(
                f"Can't find a template with the name, id or url `{name_or_id}`.\n"
                f"Go to [templates.xenon.bot](https://templates.xenon.bot) to get a list of available templates.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        data = convert_v1_to_v2(template["data"])
        channel_list = channel_tree(data.channels)
        if len(channel_list) > 1024:
            channel_list = channel_list[:1000] + "\n...\n```"

        role_list = "```{}```".format("\n".join(
            [r.name for r in sorted(data.roles, key=lambda r: r.position, reverse=True)]
        ))
        if len(role_list) > 1024:
            role_list = role_list[:1000] + "\n...\n```"

        description = template.get("description") or "No description"
        await ctx.respond(embeds=[{
            "title": f"Template Info - *{data.name}*",
            "color": Format.INFO.color,
            "fields": [
                {
                    "name": "Used By",
                    "value": f"{template['usage_count']} people",
                    "inline": True
                },
                {
                    "name": "Created By",
                    "value": f"<@{template['creator_id']}>",
                    "inline": True
                },
                {
                    "name": "Description",
                    "value": f"{description[:1000]}",
                    "inline": False
                },
                {
                    "name": "Channels",
                    "value": channel_list,
                    "inline": True
                },
                {
                    "name": "Roles",
                    "value": role_list,
                    "inline": True
                },
            ]
        }], ephemeral=True)
