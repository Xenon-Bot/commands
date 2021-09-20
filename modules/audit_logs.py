from enum import IntEnum
import pymongo
from dbots.cmd import *
from dbots import *
from datetime import datetime, timedelta


class AuditLogType(IntEnum):
    BACKUP_CREATE = 0
    BACKUP_LOAD = 1
    BACKUP_INTERVAL_ENABLE = 2
    BACKUP_INTERVAL_DISABLE = 3
    TEMPLATE_LOAD = 4
    COPY = 5
    CHATLOG_CREATE = 6
    CHATLOG_LOAD = 7
    MESSAGE_SYNC_CREATE = 8
    BAN_SYNC_CREATE = 9
    SYNC_DELETE = 10
    ROLE_SYNC_CREATE = 11
    BACKUP_SYNC_CREATE = 12  # TODO: implement listing and info


text_formats = {
    AuditLogType.BACKUP_CREATE: "<@{user}> created a backup of this server",
    AuditLogType.BACKUP_LOAD: "<@{user}> loaded a backup on this server",
    AuditLogType.BACKUP_INTERVAL_ENABLE: "<@{user}> enabled their backup interval for this server",
    AuditLogType.BACKUP_INTERVAL_DISABLE: "<@{user}> disabled their backup interval for this server",
    AuditLogType.TEMPLATE_LOAD: "<@{user}> loaded a template on this server",
    AuditLogType.COPY: "<@{user}> copied this server or pasted a copy on this server",
    AuditLogType.CHATLOG_CREATE: "<@{user}> created a chatlog of the channel <#{channel}>",
    AuditLogType.CHATLOG_LOAD: "<@{user}> loaded a chatlog in the channel <#{channel}>",
    AuditLogType.MESSAGE_SYNC_CREATE: "<@{user}> created a message sync from <#{source}> to "
                                      "<#{target}> with the id `{id}`",
    AuditLogType.BAN_SYNC_CREATE: "<@{user}> created a ban sync from the server with the id `{source}` to "
                                  "the server with the id `{target}` with the id `{id}`",
    AuditLogType.SYNC_DELETE: "<@{user}> deleted a sync with the id `{id}`",
    AuditLogType.ROLE_SYNC_CREATE: "<@{user}> created a role sync from the role with the id {source} to "
                                   "the role with the id `{target}` with the id `{id}`",
    AuditLogType.BACKUP_SYNC_CREATE: "<@{user}> created a backup sync from the server with the id `{source}` to "
                                     "the server with the id `{target}` with the id `{id}`",
}


def _serialize_type_filter(types):
    value = 0
    for t in types:
        value |= 1 << int(t)

    return str(value)


def _deserialize_type_filter(value):
    value = int(value)
    return [
        t
        for t in AuditLogType
        if value & (1 << int(t)) == 1 << int(t)
    ]


class AuditLogModule(Module):
    async def post_setup(self):
        await self.bot.db.audit_logs.create_index([("timestamp", pymongo.ASCENDING)])
        await self.bot.db.audit_logs.create_index([("user", pymongo.ASCENDING)])
        await self.bot.db.audit_logs.create_index([("guilds", pymongo.ASCENDING)])

    @Module.task(hours=1)
    async def audit_log_retention(self):
        await self.bot.db.audit_logs.delete_many({
            "timestamp": {
                "$lte": datetime.utcnow() - timedelta(days=365)
            }
        })

    @Module.command()
    async def audit(self, ctx):
        """
        Get a list of actions that were recently taken on this server
        """

    async def _audit_logs_message(self, guild_id, page, visible_types=None):
        if visible_types is None:
            visible_types = [t for t in AuditLogType]

        page = max(page, 1)
        _filter = {
            "guilds": guild_id,
            "type": {"$in": [int(t) for t in visible_types]}
        }
        total_count = await self.bot.db.audit_logs.count_documents(_filter)

        if total_count == 0:
            return dict(**create_message(
                "There **aren't any audit logs** for this server yet.",
                f=Format.INFO,
            ), ephemeral=True)

        fields = []
        async for entry in self.bot.db.audit_logs.find(
                _filter,
                sort=[("timestamp", pymongo.DESCENDING)],
                limit=10,
                skip=(page - 1) * 10
        ):
            _type = AuditLogType(entry["type"])
            fields.append(dict(
                name=datetime_to_string(entry["timestamp"]) + " UTC - *" +
                     _type.name.replace('_', ' ').title() + "*",
                value=f"{text_formats[_type].format(**entry, **entry['extra'])}"
            ))

        description = f"Displaying **{(page - 1) * 10 + 1}** - **{min(page * 10, total_count)}** " \
                      f"of **{total_count}** total entries"

        return dict(
            embeds=[dict(
                title="Audit Logs",
                fields=fields,
                color=Format.INFO.color,
                description=f"{description}\n​"
            )],
            components=[
                ActionRow(
                    SelectMenu(
                        *[
                            SelectMenuOption(
                                label=t.name.replace("_", " ").title(),
                                value=t.value,
                                default=t in visible_types
                            )
                            for t in AuditLogType
                        ],
                        min_values=1,
                        max_values=len(AuditLogType),
                        custom_id="audit_logs_filter"
                    )
                ),
                ActionRow(
                    Button(label="Previous Page", custom_id=f"audit_logs",
                           args=[str(page - 1), _serialize_type_filter(visible_types)], disabled=page <= 1),
                    Button(label="Next Page", custom_id=f"audit_logs",
                           args=[str(page + 1), _serialize_type_filter(visible_types)],
                           disabled=total_count <= page * 10)
                )
            ],
            ephemeral=True
        )

    @audit.sub_command(extends=dict(
        page="The page to display (default 1)"
    ))
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.cooldown(2, 10, bucket=checks.CooldownType.GUILD)
    async def logs(self, ctx, page: int = 1):
        """
        Get a list of actions that were recently taken on this server
        """
        data = await self._audit_logs_message(ctx.guild_id, page)
        await ctx.respond(**data)

    @Module.component(name="audit_logs")
    async def logs_page(self, ctx, page, filter_value):
        data = await self._audit_logs_message(ctx.guild_id, int(page), _deserialize_type_filter(filter_value))
        await ctx.update(**data)

    @Module.component(name="audit_logs_filter")
    async def logs_filter(self, ctx):
        visible_types = [AuditLogType(int(t)) for t in ctx.values]
        data = await self._audit_logs_message(ctx.guild_id, 1, visible_types)
        await ctx.update(**data)
