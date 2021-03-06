from enum import IntEnum
import pymongo
import asyncio
from dbots.cmd import *


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


text_formats = {
    AuditLogType.BACKUP_CREATE: "<@{user}> created a backup of this server",
    AuditLogType.BACKUP_LOAD: "<@{user}> loaded a backup on this server",
    AuditLogType.BACKUP_INTERVAL_ENABLE: "<@{user}> enabled their backup interval for this server",
    AuditLogType.BACKUP_INTERVAL_DISABLE: "<@{user}> disabled their backup interval for this server",
    AuditLogType.TEMPLATE_LOAD: "<@{user}> loaded a template on this server",
    AuditLogType.COPY: "<@{user}> copied the server with the id `{source}` to the server with the id `{target}`",
    AuditLogType.CHATLOG_CREATE: "<@{user}> created a chatlog of the channel <#{channel}>",
    AuditLogType.CHATLOG_LOAD: "<@{user}> loaded a chatlog in the channel <#{channel}>",
    AuditLogType.MESSAGE_SYNC_CREATE: "<@{user}> created a message sync from <#{source}> to "
                                      "<#{target}> with the id `{id}`",
    AuditLogType.BAN_SYNC_CREATE: "<@{user}> created a ban sync from the server with the id `{source}` to "
                                  "the server with the id `{target}` with the id `{id}`",
    AuditLogType.SYNC_DELETE: "<@{user}> deleted a sync with the id `{id}`",
    AuditLogType.ROLE_SYNC_CREATE: "<@{user}> created a role sync from the role with the id {source} to "
                                   "the role with the id {target} with the id `{id}`",
}


class AuditLogList(object):
    embed_kwargs = {"title": "Audit Logs"}

    async def get_items(self):
        args = {
            "limit": 10,
            "skip": self.page * 10,
            "sort": [("timestamp", pymongo.DESCENDING)],
            "filter": {
                "guilds": self.ctx.guild_id,
            }
        }
        logs = self.ctx.bot.db.audit_logs.find(**args)
        items = []
        async for audit_log in logs:
            type = AuditLogType(audit_log["type"])
            items.append((
                datetime_to_string(audit_log["timestamp"]) + " UTC - *" + type.name.replace('_', ' ').title() + "*",
                f"{text_formats[type].format(**audit_log, **audit_log['extra'])}"
            ))

        return items


class AuditLogModule(Module):
    # TODO: audit log retention

    @Module.command()
    async def audit(self, ctx):
        """
        Get a list of actions that were recently taken on this server
        """

    @audit.sub_command()
    @checks.has_permissions_level()
    @checks.cooldown(1, 10, bucket=checks.CooldownType.GUILD)
    async def logs(self, ctx):
        """
        Get a list of actions that were recently taken on this server
        """
        await ctx.ack_with_source()
        await asyncio.sleep(0.1)

        menu = AuditLogList(ctx)
        await menu.start()
