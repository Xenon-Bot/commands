from dbots.cmd import *


class SyncModule(Module):
    @Module.command()
    async def sync(self, ctx):
        """
        Sync events from one server or channel to another
        """

    @sync.sub_command()
    @guild_only
    async def list(self, ctx):
        """
        List all syncs related to this server
        """

    @sync.sub_command()
    @guild_only
    async def delete(self, ctx):
        """
        Delete a sync that is related to this server
        """

    @sync.sub_command()
    @guild_only
    async def messages(self, ctx):
        """
        Sync new messages from one channel to another
        """

    @sync.sub_command()
    @guild_only
    async def bans(self, ctx):
        """
        Sync new bans and unbans from one server to another
        """

    @sync.sub_command()
    @guild_only
    async def role(self, ctx):
        """
        Sync role assignments for one role to another
        """
