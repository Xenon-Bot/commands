from dbots.cmd import *

from util import PremiumLevel

MAX_MESSAGE_COUNT = {
    PremiumLevel.NONE: 0,
    PremiumLevel.ONE: 250,
    PremiumLevel.TWO: 500,
    PremiumLevel.THREE: 1000
}


class ChatlogModule(Module):
    @Module.command()
    async def chatlog(self, ctx):
        """
        Create, load and manage your channel chatlogs
        """

    @chatlog.sub_command()
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("view_channel", "read_message_history")
    async def create(self, ctx, message_count: int = 1000):
        """
        Create a chatlog of this channel
        """

    @chatlog.sub_command()
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("manage_webhooks")
    @checks.not_in_maintenance
    async def load(self, ctx, chatlog_id, message_count: int = 1000):
        """
        Load a previously created chatlog in this channel
        """

    @chatlog.sub_command()
    async def info(self, ctx, chatlog_id):
        """
        Get information about a previously created chatlog
        """

    @chatlog.sub_command()
    async def list(self, ctx):
        """
        Get a list of all your previously created chatlogs
        """

    @chatlog.sub_command()
    async def delete(self, ctx, chatlog_id):
        """
        Delete one of your previously created chatlogs
        """

    @chatlog.sub_command()
    async def purge(self, ctx):
        """
        Delete all your previously created chatlogs
        """
