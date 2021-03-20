from dbots.cmd import *

PREMIUM_ONLY_TEXT = "This command can **only** be used with **Xenon Premium**.\n\n" \
                    "**Xenon Premium** is the **paid version** of Xenon.\n" \
                    "You can buy it on [patreon](https://www.patreon.com/merlinfuchs) " \
                    "and find a detailed list of perks [here](https://wiki.xenon.bot/premium)"


class PremiumModule(Module):
    @Module.command()
    async def chatlog(self, ctx):
        """
        Save & load messages from individual channels

        You can find more help on the [wiki](https://wiki.xenon.bot/chatlog)
        """
        await ctx.respond(PREMIUM_ONLY_TEXT, ephemeral=True)

    @Module.command()
    async def sync(self, ctx):
        """
        Sync messages, bans and role assignments between different servers and channels

        You can find more help on the [wiki](https://wiki.xenon.bot/sync)
        """
        await ctx.respond(PREMIUM_ONLY_TEXT, ephemeral=True)

    @Module.command()
    async def copy(self, ctx):
        """
        Copy a server without creating a backup
        """
        await ctx.respond(PREMIUM_ONLY_TEXT, ephemeral=True)
