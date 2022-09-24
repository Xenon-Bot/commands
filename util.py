from enum import IntEnum

import config
from dbots.cmd import Check

__all__ = (
    "PremiumLevel",
    "premium_required",
    "entitlement_required",
    "PREMIUM_REQUIRED_TEXT",
    "can_upsell"
)

PREMIUM_REQUIRED_TEXT = "You **need** to buy **Xenon Premium** to be able to use this bot and its commands.\n\n" \
                        "You can **buy Premium [here](<https://patreon.com/merlinfuchs>)** and " \
                        "get a full list of features [here](<https://wiki.xenon.bot/premium>).\n\n\n" \
                        "*If you have already bought Xenon Premium please click " \
                        "[here](<https://wiki.xenon.bot/premium#redeem-perks>)*."


class PremiumLevel(IntEnum):
    NONE = 0
    ONE = 1
    TWO = 2
    THREE = 3


def can_upsell(ctx):
    return config.CAN_UPSELL and ctx.guild_id in {"1023015746378403962", "1023015685829447751"}


@Check
async def premium_required(ctx, **_):
    if ctx.premium_level == PremiumLevel.NONE:
        await ctx.respond(
            content=PREMIUM_REQUIRED_TEXT,
            ephemeral=True
        )
        return False

    return True


@Check
async def entitlement_required(ctx, **_):
    if len(ctx.entitlement_sku_ids) == 0 and ctx.premium_level == PremiumLevel.NONE:
        if can_upsell(ctx):
            await ctx.upsell()
        else:
            await ctx.respond(
                content=PREMIUM_REQUIRED_TEXT,
                ephemeral=True
            )
        return False

    return True
