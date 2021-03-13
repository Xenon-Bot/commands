from dbots import Role, Channel, rest, Message
from dbots.cmd import *
import re
import asyncio
from datetime import timedelta, datetime
from grpclib.exceptions import GRPCError
from dbots.protos import backups_pb2
import grpclib

from .audit_logs import AuditLogType
from .backups import warning_list, convert_v1_to_v2, channel_tree


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

        try:
            data = await self.bot.http.get_template(identifier)
            guild = data["serialized_source_guild"]
            return {
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

    @template.sub_command(
        extends=dict(
            identifier=dict(
                description="The name, id or url of the template that you want to load"
            )
        )
    )
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    @checks.not_in_maintenance
    @checks.cooldown(1, 5 * 60, bucket=checks.CooldownType.GUILD, manual=True)
    async def load(self, ctx, name_or_id, options=""):
        """
        Load one of the public templates

        You can find more help on the [wiki](https://wiki.xenon.bot/templates#loading-a-template).
        """
        template = await self._get_template(name_or_id)
        data = convert_v1_to_v2(template["data"])
        if template is None:
            await ctx.respond_with_source(**create_message(
                f"Can't find a template with the name, id or url `{template}`.\n"
                f"Go to [templates.xenon.bot](https://templates.xenon.bot) to get a list of available templates.",
                f=Format.ERROR
            ))
            return

        allowed = ("delete_roles", "delete_channels", "roles", "channels", "settings")
        parsed_options = {"delete_roles", "delete_channels", "roles", "channels", "settings"}
        for option in options.replace("-", "_").split(" "):
            if option == "!*":
                parsed_options.clear()
            elif option == "*":
                parsed_options = set(allowed)
            elif option.startswith("!"):
                try:
                    parsed_options.remove(option[1:])
                except KeyError:
                    pass
            elif option in allowed:
                parsed_options.add(option)

        # Require a confirmation by the user
        await ctx.respond(**create_message(
            "**Hey, be careful!** The following actions will be taken on this server and **can not be undone**:\n\n"
            f"{warning_list(parsed_options)}\n\n"
            f"Type `/confirm` to confirm this action and continue.",
            f=Format.WARNING
        ))

        try:
            await self.bot.wait_for_confirmation(ctx, timeout=60)
        except asyncio.TimeoutError:
            await ctx.delete_response()
            return

        await ctx.count_cooldown()

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
            ids = translator["ids"]

        await ctx.edit_response(**create_message(
            "**The template is now loading**. Please be patient, this can take a while!\n\n"
            "Use `/template status` to get the current status and `/template cancel` to cancel the process.\n\n"
            "*This message will not be updated.*",
            f=Format.INFO
        ))
        await asyncio.sleep(5)

        try:
            replies = await self.bot.rpc.backups.Load(backups_pb2.LoadRequest(
                guild_id=ctx.guild_id,
                options=list(parsed_options),
                message_count=0,
                data=data,
                reason="Template loaded by " + str(ctx.author),
                ids=ids
            ))
        except GRPCError as e:
            if e.status == grpclib.Status.ALREADY_EXISTS:
                await ctx.edit_response(**create_message(
                    f"There is **already a loading process running** on this server.\n"
                    f"Please wait for it to finish or use `/template cancel` to stop it.",
                    f=Format.ERROR
                ))
                return
            else:
                raise

        try:
            await ctx.edit_response(**create_message(
                f"Successfully **loaded the template**.",
                f=Format.SUCCESS
            ))
        except rest.HTTPNotFound:
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
    @checks.has_permissions_level(destructive=True)
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
                ))
                return
            else:
                raise

        await ctx.respond(**create_message(
            "Successfully **cancelled the currently running loading process** on this server.",
            f=Format.SUCCESS
        ))

    @template.sub_command()
    @checks.has_permissions_level()
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
                ))
                return
            else:
                raise

        await ctx.respond(**create_message(
            f"{reply.status} ...\n\n"
            f"*Please be patient, this could take a while.*",
            title="Loader Status",
            f=Format.INFO
        ))

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

    @template.sub_command(
        extends=dict(
            identifier=dict(
                description="The name, id or url of the template that you want to load"
            )
        )
    )
    async def info(self, ctx, name_or_id):
        """
        Get information about a public template
        """
        template = await self._get_template(name_or_id)
        data = convert_v1_to_v2(template["data"])
        if template is None:
            await ctx.respond_with_source(**create_message(
                f"Can't find a template with the name, id or url `{template}`.\n"
                f"Go to [templates.xenon.bot](https://templates.xenon.bot) to get a list of available templates.",
                f=Format.ERROR
            ))
            return

        channel_list = channel_tree(data.channels)
        if len(channel_list) > 1024:
            channel_list = channel_list[:1000] + "\n...\n```"

        role_list = "```{}```".format("\n".join(
            [r.name for r in sorted(data.roles, key=lambda r: r.position, reverse=True)]
        ))
        if len(role_list) > 1024:
            role_list = role_list[:1000] + "\n...\n```"

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
                    "value": f"{template['description'][:1000]}",
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
        }])
