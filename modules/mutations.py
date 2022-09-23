from dbots.cmd import *
from dbots import *
from util import *


class MutationsModule(Module):
    @Module.command(default_member_permissions=Permissions.FlagList.administrator, dm_permission=False)
    async def changes(self, ctx):
        """
        View and revert changes made to your Discord server
        """

    @changes.sub_command()
    @checks.guild_only
    @entitlement_required
    @checks.has_permissions_level()
    @checks.cooldown(1, 30, bucket=checks.CooldownType.GUILD, manual=True)
    async def enable(self, ctx):
        """
        Enable change logging for this server
        """

    @changes.sub_command()
    @checks.guild_only
    @entitlement_required
    @checks.has_permissions_level()
    @checks.cooldown(1, 30, bucket=checks.CooldownType.GUILD, manual=True)
    async def disable(self, ctx):
        """
        Disable change logging for this server
        """

    @changes.sub_command()
    @checks.guild_only
    @entitlement_required
    @checks.has_permissions_level()
    @checks.cooldown(1, 30, bucket=checks.CooldownType.GUILD, manual=True)
    async def list(self, ctx):
        """
        List changes that have recently been made to your server
        """

    @changes.sub_command()
    @checks.guild_only
    @entitlement_required
    @checks.has_permissions_level(destructive=True)
    @checks.cooldown(1, 30, bucket=checks.CooldownType.GUILD, manual=True)
    async def revert(self, ctx):
        """
        Revert changes that have recently been made to your server
        """
