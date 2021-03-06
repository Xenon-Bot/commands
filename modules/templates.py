from dbots import Role, Channel, rest, Message
from dbots.cmd import *
import re
import asyncio
from datetime import timedelta, datetime

from .audit_logs import AuditLogType


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
                    "roles": [
                        {
                            "position": pos,
                            **r
                        }
                        for pos, r in enumerate(guild.pop("roles", []))
                    ],
                    "mfa_level": 0,
                    **guild
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
            "Please use https://templates.xenon.bot to add new templates, "
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
    @checks.cooldown(1, 60, bucket=checks.CooldownType.GUILD, manual=True)
    async def load(self, ctx, identifier, options=""):
        """
        Load one of the public templates

        You can find more help on the [wiki](https://wiki.xenon.bot/templates#loading-a-template).
        """
        template = await self._get_template(identifier)
        if template is None:
            await ctx.respond_with_source(**create_message(
                f"Can't find a template with the name, id or url `{template}`.\n"
                f"Go to [templates.xenon.bot](https://templates.xenon.bot) to get a list of available templates.",
                f=Format.ERROR
            ))
            return

        if await ctx.bot.redis.exists(f"cmd:loaders:{ctx.guild_id}"):
            await ctx.respond_with_source(**create_message(
                "There is **already** a backup or template loader **running**. "
                "You can't start more than one at the same time.\n"
                "You have to **wait until it's done** or use `/template cancel` to cancel the loader..",
                f=Format.ERROR
            ))
            return

        await ctx.ack_with_source()
        await asyncio.sleep(0.2)

        # Fill options object
        parsed_options = LoaderOptions("delete-channels delete-roles channels roles settings")
        parsed_options.update(options)
        parsed_options.update("!messages !members !bans")

        # Require a confirmation by the user
        status_msg = Message(await ctx.respond(**create_message(
            warning_text(parsed_options),
            f=Format.WARNING
        )))

        confirmed = await reaction_confirmation(ctx.bot, status_msg, ctx.author.id)
        if not confirmed:
            await ctx.edit_response(**create_message(
                "You didn't confirm to load the template so the **loading process was cancelled**.\n"
                f"If this was not intended use `/template load template: {identifier}` to try again.",
                f=Format.INFO
            ), message_id=status_msg.id)
            return

        await ctx.count_cooldown()

        # TODO: Publish loaders:start event

        loader = GuildLoader(
            self.bot,
            ctx.guild_id,
            template["data"],
            options=parsed_options,
            ignore=[ctx.channel_id],
            reason="Template loaded by " + str(ctx.author)
        )

        # Inject previous id translators if available
        translator = await ctx.bot.db.id_translators.find_one({
            "target_id": ctx.guild_id,
            "source_id": loader.data["id"]
        })
        if translator is not None:
            loader.ids.update(translator["ids"])

        try:
            async for option in run_loader(loader):
                # TODO: Publish loaders:status event
                try:
                    await ctx.edit_response(**create_message(
                        status_text(parsed_options, option),
                        title="Loading Status",
                        f=Format.PLEASE_WAIT
                    ), message_id=status_msg.id)
                except rest.HTTPException:
                    pass

        except asyncio.CancelledError:
            try:
                await ctx.edit_response(**create_message(
                    "The **loading process was cancelled**.",
                    f=Format.ERROR
                ), message_id=status_msg.id)
            except rest.HTTPException:
                pass

        except RoleRateLimit as e:
            remaining = timedelta(hours=48)
            if e.ratelimit is not None:
                remaining = timedelta(seconds=e.ratelimit.delta)

            try:
                await ctx.edit_response(**create_message(
                    "Seems like you **hit** the `250 per 48 hours` **role creation limit** of discord.\n"
                    "Xenon is only allowed to create 250 roles in a time frame of 48 hours.\n\n"
                    f"**You have to wait** `{timedelta_to_string(remaining, precision='m')}` "
                    f"before loading another backup or template containing roles.\n\n"
                    f"**This is a discord limitation and there is no way around it.**",
                    f=Format.ERROR
                ), message_id=status_msg.id)
            except rest.HTTPException:
                pass

        else:
            try:
                await ctx.edit_response(**create_message(
                    f"Successfully **loaded the template**.",
                    f=Format.SUCCESS
                ), message_id=status_msg.id)
            except rest.HTTPException:
                pass

            if parsed_options.get("delete_channels"):
                await asyncio.sleep(5)
                try:
                    await ctx.bot.http.delete_channel(ctx.channel_id)
                except rest.HTTPException:
                    pass

        # Save ids for later use and recovery
        await ctx.bot.db.id_translators.update_one(
            {
                "target_id": ctx.guild_id,
                "source_id": loader.data["id"],
            },
            {
                "$set": {
                    "target_id": ctx.guild_id,
                    "source_id": loader.data["id"],
                    **{
                        f"ids.{s}": t
                        for s, t in loader.ids.items()
                    }
                },
                "$addToSet": {
                    "loaders": ctx.author.id
                }
            },
            upsert=True
        )

        # TODO: Publish loaders:done event

        # Create audit log entry
        await self.bot.db.audit_logs.insert_one({
            "type": AuditLogType.TEMPLATE_LOAD,
            "timestamp": datetime.utcnow(),
            "guilds": [ctx.guild_id],
            "user": ctx.author.id,
            "extra": {}
        })

    @template.sub_command()
    @checks.has_permissions_level(destructive=True)
    async def cancel(self, ctx):
        """
        Cancel the currently running loading process on this server
        """
        await ctx.bot.redis.delete(f"cmd:loaders:{ctx.guild_id}")
        await ctx.respond_with_source(**create_message(
            "Successfully **cancelled the currently running loader** on this server.",
            f=Format.SUCCESS
        ))

    @template.sub_command()
    @checks.has_permissions_level()
    async def status(self, ctx):
        """
        Get the status of the currently running loading process
        """
        status = await ctx.bot.redis.get(f"cmd:loaders:{ctx.guild_id}")
        if status is None:
            await ctx.respond_with_source(**create_message(
                "There is currently no loader running on this server",
                f=Format.ERROR
            ))
            return

        status_text = option_text[status.decode()]
        await ctx.respond_with_source(**create_message(
            f"{status_text} ...\n\n"
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
    async def info(self, ctx, identifier):
        """
        Get information about a public template
        """
        template = await self._get_template(identifier)
        if template is None:
            await ctx.respond_with_source(**create_message(
                f"Can't find a template with the name, id or url `{template}`.\n"
                f"Go to [templates.xenon.bot](https://templates.xenon.bot) to get a list of available templates.",
                f=Format.ERROR
            ))
            return

        data = template["data"]

        channel_list = channel_tree([Channel(c) for c in data["channels"]])
        if len(channel_list) > 1024:
            channel_list = channel_list[:1000] + "\n...\n```"

        roles = [Role(r) for r in data["roles"]]
        role_list = "```{}```".format("\n".join(
            [r.name for r in sorted(roles, key=lambda r: r.position, reverse=True)]
        ))
        if len(role_list) > 1024:
            role_list = role_list[:1000] + "\n...\n```"

        await ctx.respond_with_source(embeds=[{
            "title": f"Template Info - *{data['name']}*",
            "color": Format.INFO.color,
            "fields": [
                {
                    "name": "Creator",
                    "value": f"<@{template['creator_id']}>",
                    "inline": False
                },
                {
                    "name": "Uses",
                    "value": str(template["usage_count"]),
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
