from dbots.cmd import *


class ClipboardModule(Module):
    @Module.command()
    async def clipboard(self, ctx):
        """
        Save, load and manage your clipboard (similar to ctrl+c & ctrl+v)
        """

    @clipboard.sub_command()
    @checks.guild_only
    @checks.has_permissions_level()
    @checks.bot_has_permissions("administrator")
    async def copy(self, ctx):
        """
        Save this server to your clipboard
        """

    @clipboard.sub_command()
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    @checks.not_in_maintenance
    async def paste(self, ctx, message_count: int = 250, options=""):
        """
        Load the server from your clipboard on this server
        """

    @clipboard.sub_command()
    async def view(self, ctx):
        """
        Save this server to your clipboard
        """

    @clipboard.sub_command()
    async def clear(self, ctx):
        """
        Save this server to your clipboard
        """
