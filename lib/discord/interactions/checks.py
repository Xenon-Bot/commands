import functools

from .formatter import *
from .response import *
from ..utils import *

__all__ = (
    "guild_only",
    "dm_only",
)


def check(check_func):
    def _predicate(handler):
        @functools.wraps(handler)
        def _wrapped_handler(*args, **kwargs):
            res = check_func(*args[1:], **kwargs)
            if isinstance(res, InteractionResponse):
                return single_async_yield(res)

            return handler(*args, **kwargs)

        return _wrapped_handler

    return _predicate


@check
def guild_only(ctx, **_):
    if ctx.guild_id is None:
        return create_response(
            "This command can **only** be used **inside a server**.",
            f=Format.ERROR
        )

    return None


@check
def dm_only(ctx, **_):
    if ctx.guild_id is not None:
        return create_response(
            "This command can **only** be used inside **direct messages**.",
            f=Format.ERROR
        )

    return None
