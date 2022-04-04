from enum import IntEnum


__all__ = (
    "ChannelType",
    "DefaultMessageNotifications",
    "ExplicitContentFilter",
    "MFALevel",
    "VerificationLevel",
    "MessageType",
    "WebhookType",
    "PremiumType",
    "PremiumTier",
    "MutationType"
)


class ChannelType(IntEnum):
    GUILD_TEXT = 0
    DM = 1
    GUILD_VOICE = 2
    GROUP_DM = 3
    GUILD_CATEGORY = 4
    GUILD_NEWS = 5
    GUILD_STORE = 6
    PUBLIC_GUILD_THREAD = 11
    PRIVATE_GUILD_THREAD = 12
    GUILD_STAGE = 13


class DefaultMessageNotifications(IntEnum):
    ALL_MESSAGES = 0
    ONLY_MENTIONS = 1


class ExplicitContentFilter(IntEnum):
    DISABLED = 0
    MEMBERS_WITHOUT_ROLES = 1
    ALL_MEMBERS = 2


class MFALevel(IntEnum):
    NONE = 0
    ELEVATED = 1


class VerificationLevel(IntEnum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4


class MessageType(IntEnum):
    DEFAULT = 0
    RECIPIENT_ADD = 1
    RECIPIENT_REMOVE = 2
    CALL = 3
    CHANNEL_NAME_CHANGE = 4
    CHANNEL_ICON_CHANGE = 5
    CHANNEL_PINNED_MESSAGE = 6
    GUILD_MEMBER_JOIN = 7
    USER_PREMIUM_GUILD_SUBSCRIPTION = 8
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_1 = 9
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_2 = 10
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_3 = 11
    CHANNEL_FOLLOW_ADD = 12
    GUILD_DISCOVERY_DISQUALIFIED = 14
    GUILD_DISCOVERY_REQUALIFIED = 15
    GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING = 16
    GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING = 17
    THREAD_CREATED = 18
    REPLY = 19
    APPLICATION_COMMAND = 20
    THREAD_STARTER_MESSAGE = 21
    GUILD_INVITE_REMINDER = 22
    CONTEXT_MENU_COMMAND = 23
    UNKNOWN_1 = 24
    UNKNOWN_2 = 25
    UNKNOWN_3 = 26
    UNKNOWN_4 = 27
    UNKNOWN_5 = 28
    UNKNOWN_6 = 29
    UNKNOWN_7 = 30


class WebhookType(IntEnum):
    INCOMING = 1
    CHANNEL_FOLLOWER = 2


class PremiumType(IntEnum):
    NONE = 0
    NITRO_CLASSIC = 1
    NITRO = 2


class PremiumTier(IntEnum):
    NONE = 0
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


class MutationType(IntEnum):
    CHANNEL_CREATE = 0
    CHANNEL_UPDATE = 1
    CHANNEL_DELETE = 2
    ROLE_CREATE = 3
    ROLE_UPDATE = 4
    ROLE_DELETE = 5
    GUILD_UPDATE = 6
    MEMBER_UPDATE = 7
