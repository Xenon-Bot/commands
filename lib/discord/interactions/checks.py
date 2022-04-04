import inspect

from .formatter import *
from .response import *

__all__ = (
    "Check",
    "guild_only",
    "dm_only",
)


class Check:
    def __init__(self, callable, next=None):
        self.callable = callable
        self.next = next

    def __call__(self, next):
        self.next = next
        return self

    async def run(self, ctx, **kwargs):
        result = self.callable(ctx, **kwargs)
        if inspect.isawaitable(result):
            result = await result

        return result


@Check
async def guild_only(ctx, **_):
    if ctx.guild_id is None:
        return InteractionResponse.message(**create_message(
            "This command can **only** be used **inside a server**.",
            f=Format.ERROR
        ), ephemeral=True)

    return None


@Check
async def dm_only(ctx, **_):
    if ctx.guild_id is not None:
        await ctx.respond(**create_message(
            "This command can **only** be used inside **direct messages**.",
            f=Format.ERROR
        ), ephemeral=True)
        return False

    return True
