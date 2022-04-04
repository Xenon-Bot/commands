import asyncio
import sys
import traceback

from lib.discord import *


class Xenon(InteractionBot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._invite = None
        self._support_invite = None

        self.component(self._delete_button, name="delete")

    async def _delete_button(self, ctx):
        ctx.defer()
        await ctx.delete_response()

    async def on_command_error(self, ctx, e):
        if isinstance(e, asyncio.CancelledError):
            raise e

        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))

        error_id = unique_id()
        print(f"Command Error #{error_id}:\n", tb, file=sys.stderr)
        try:
            await ctx.respond(**create_message(
                "An unexpected error occurred. Please report this on the "
                f"[Support Server](<{await ctx.bot.get_support_invite()}>).\n\n"
                f"**Error Code**: `{error_id.upper()}`",
                f=Format.ERROR
            ), ephemeral=True)
        except HTTPException:
            pass

    async def get_invite(self):
        if self._invite:
            return self._invite

        invite = "https://xenon.bot/invite"
        while "discord.com" not in invite:
            async with self.session.get(invite, allow_redirects=False) as resp:
                if 400 > resp.status >= 300:
                    invite = resp.headers["Location"]
                else:
                    break

        self._invite = invite
        return invite

    async def get_support_invite(self):
        if self._support_invite:
            return self._support_invite

        invite = "https://xenon.bot/discord"
        while "discord.com" not in invite:
            async with self.session.get(invite, allow_redirects=False) as resp:
                if 400 > resp.status >= 300:
                    invite = resp.headers["Location"]
                else:
                    break

        self._support_invite = invite
        return invite
