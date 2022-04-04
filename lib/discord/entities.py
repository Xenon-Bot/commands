from datetime import datetime
import re

from .enums import *
from .flags import *

__all__ = (
    "Entity",
    "Snowflake",
    "Guild",
    "Channel",
    "Role",
    "User",
    "Member",
    "MessageReaction",
    "MessageAttachment",
    "Message",
    "Webhook"
)

DISCORD_EPOCH = 1420070400000


def parse_time(timestamp):
    if timestamp:
        return datetime(*map(int, re.split(r'[^\d]', timestamp.replace('+00:00', ''))))

    return None


def cdn_url(path):
    return f"https://cdn.discordapp.com/{path}"


class Entity:
    __slots__ = ("id", "relay", "http")

    def __init__(self):
        self.relay = None
        self.http = None

    def __hash__(self):
        return int(self.id) >> 22

    def __eq__(self, other):
        return isinstance(other, self.__class__) and other.id == self.id

    def __ne__(self, other):
        if isinstance(other, self.__class__):
            return other.id != self.id

        return True

    def to_dict(self):
        return {
            "id": self.id
        }

    @property
    def created_at(self):
        return datetime.utcfromtimestamp(((int(self.id) >> 22) + DISCORD_EPOCH) / 1000)


class Snowflake(Entity):
    def __init__(self, id):
        super().__init__()
        self.id = id


class PartialGuild(Entity):
    __slots__ = ("id", "unavailable")

    def __init__(self, data):
        super().__init__()
        self.id = data["id"]
        self.unavailable = data.get("unavailable", False)

    def to_dict(self):
        return {
            "id": self.id,
            "unavailable": self.unavailable
        }


class Guild(PartialGuild):
    __slots__ = ("_data", "name", "icon", "splash", "discovery_splash", "owner", "owner_id", "permissions", "region",
                 "afk_channel_id", "afk_timeout", "widget_enabled", "widget_channel_id", "verification_level",
                 "default_message_notifications", "explicit_content_filter", "roles", "emojis", "features", "mfa_level",
                 "application_id", "system_channel_id", "system_channel_flags", "rules_channel_id", "joined_at",
                 "large", "member_count", "voice_states", "members", "channels", "presences", "max_presences",
                 "max_members", "vanity_url_code", "description", "banner", "premium_tier",
                 "premium_subscription_count", "preferred_locale", "public_updates_channel_id",
                 "max_video_channel_users", "approximate_member_count", "approximate_presence_count")

    def __init__(self, data):
        super().__init__(data)
        self._data = data

        self.name = data["name"]
        self.icon = data["icon"]
        self.splash = data["splash"]
        self.discovery_splash = data["discovery_splash"]
        self.owner = data.get("owner")
        self.owner_id = data["owner_id"]
        self.permissions = Permissions(int(data["permissions"])) if "permissions" in data else None
        self.region = data["region"]
        self.afk_channel_id = data["afk_channel_id"]
        self.afk_timeout = data["afk_timeout"]
        self.widget_enabled = data["widget_enabled"]
        self.widget_channel_id = data["widget_channel_id"]
        self.verification_level = VerificationLevel(data["verification_level"])
        self.default_message_notifications = DefaultMessageNotifications(data["default_message_notifications"])
        self.explicit_content_filter = ExplicitContentFilter(data["explicit_content_filter"])
        self.roles = [Role(r) for r in data["roles"]]
        self.emojis = data["emojis"]
        self.features = data["features"]
        self.mfa_level = MFALevel(data["mfa_level"])
        self.application_id = data["application_id"]
        self.system_channel_id = data["system_channel_id"]
        self.system_channel_flags = SystemChannelFlags(data["system_channel_flags"])
        self.rules_channel_id = data["rules_channel_id"]
        self.joined_at = parse_time(data.get("joined_at"))
        self.large = data.get("large", False)
        self.member_count = data.get("member_count")
        self.voice_states = data.get("voice_states", [])
        self.members = [Member(m) for m in data.get("members", [])]
        self.channels = [Channel(c) for c in data.get("channels", [])]
        self.presences = data.get("presences", [])
        self.max_presences = data.get("max_presences")
        self.max_members = data.get("max_members")
        self.vanity_url_code = data["vanity_url_code"]
        self.description = data["description"]
        self.banner = data["banner"]
        self.premium_tier = PremiumTier(data["premium_tier"])
        self.premium_subscription_count = data.get("premium_subscription_count")
        self.preferred_locale = data["preferred_locale"]
        self.public_updates_channel_id = data["public_updates_channel_id"]
        self.max_video_channel_users = data.get("max_video_channel_users")
        self.approximate_member_count = data.get("approximate_member_count")
        self.approximate_presence_count = data.get("approximate_presence_count")

    def to_dict(self):
        return self._data

    @property
    def icon_url(self):
        return self.icon_url_as()

    @property
    def splash_url(self):
        return self.splash_url_as()

    @property
    def discovery_splash_url(self):
        return self.discovery_splash_url_as()

    @property
    def banner_url(self):
        return self.banner_url_as()

    @property
    def default_role(self):
        for role in self.roles:
            if role.id == self.id:
                return role

    def icon_url_as(self, fmt=None, static_fmt="webp"):
        if self.icon is None:
            return None

        if fmt is not None:
            return cdn_url(f"icons/{self.id}/{self.icon}.{fmt}")

        elif self.icon.startswith("a_"):
            return cdn_url(f"icons/{self.id}/{self.icon}.gif")

        else:
            return cdn_url(f"icons/{self.id}/{self.icon}.{static_fmt}")

    def splash_url_as(self, fmt="webp"):
        if self.splash is None:
            return None

        return cdn_url(f"icons/{self.id}/{self.icon}.{fmt}")

    def discovery_splash_url_as(self, fmt="webp"):
        if self.discovery_splash is None:
            return None

        return cdn_url(f"discovery-splashes/{self.id}/{self.discovery_splash}.{fmt}")

    def banner_url_as(self, fmt="webp"):
        if self.banner is None:
            return None

        return cdn_url(f"banners/{self.id}/{self.banner}.{fmt}")

    def compute_permissions(self, member):
        if self.owner == member.id:
            return Permissions.all()

        perms = Permissions.none()
        roles = sorted(self.roles, key=lambda r: r.position)
        for role in roles:
            if role.id in member.roles:
                perms.value |= role.permissions.value

        return perms

    def get_role(self, role_id):
        for role in self.roles:
            if role.id == role_id:
                return role

        return None

    def get_channel(self, channel_id):
        for channel in self.channels:
            if channel.id == channel_id:
                return channel

        return None


class Channel(Entity):
    __slots__ = ("_data", "id", "type", "guild_id", "position", "permission_overwrites", "name", "topic", "nsfw",
                 "last_message_id", "bitrate", "user_limit", "rate_limit_per_user", "recipients", "icon", "owner_id",
                 "application_id", "parent_id", "last_pin_timestamp")

    def __init__(self, data):
        super().__init__()
        self._data = data

        self.id = data["id"]
        self.type = ChannelType(data["type"])
        self.guild_id = data.get("guild_id")
        self.position = data.get("position")
        self.permission_overwrites = [
            (ov["id"], ov["type"], PermissionOverwrites.from_pair(
                Permissions(int(ov["allow"])),
                Permissions(int(ov["deny"]))
            ))
            for ov in data.get("permission_overwrites", [])
        ]
        self.name = data.get("name")
        self.topic = data.get("topic")
        self.nsfw = data.get("nsfw")
        self.last_message_id = data.get("last_message_id")
        self.bitrate = data.get("bitrate")
        self.user_limit = data.get("user_limit")
        self.rate_limit_per_user = data.get("rate_limit_per_user")
        self.recipients = data.get("recipients")
        self.icon = data.get("icon")
        self.owner_id = data.get("owner_id")
        self.application_id = data.get("application_id")
        self.parent_id = data.get("parent_id")
        self.last_pin_timestamp = data.get("last_pin_timestamp")

    def to_dict(self):
        return self._data

    def avatar_url_as(self, fmt="webp"):
        return cdn_url(f"app-icons/{self.application_id}/{self.icon}.{fmt}")

    @property
    def avatar_url(self):
        return self.avatar_url_as()

    @property
    def can_send(self):
        return self.type == ChannelType.GUILD_TEXT or self.type == ChannelType.GUILD_NEWS


class Role(Entity):
    __slots__ = ("name", "color", "hoist", "position", "permissions", "managed", "mentionable", "guild_id")

    def __init__(self, data):
        super().__init__()
        self.id = data["id"]
        self.name = data["name"]
        self.color = data["color"]
        self.hoist = data["hoist"]
        self.position = data["position"]
        self.permissions = Permissions(int(data["permissions"]))
        self.managed = data.get("managed", False)
        self.mentionable = data["mentionable"]
        self.guild_id = data.get("guild_id")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "hoist": self.hoist,
            "position": self.position,
            "permissions": str(self.permissions.value),
            "managed": self.managed,
            "mentionable": self.mentionable,
            "guild_id": self.guild_id
        }


class User(Entity):
    __slots__ = ("_data", "username", "discriminator", "avatar", "bot", "system", "mfa_enabled", "locale", "verified",
                 "email", "flags", "premium_type", "public_flags")

    def __init__(self, data):
        super().__init__()
        self._data = data

        self.id = data["id"]
        self.username = data["username"]
        self.discriminator = data["discriminator"]
        self.avatar = data["avatar"]
        self.bot = data.get("bot", False)
        self.system = data.get("system", False)
        self.mfa_enabled = data.get("mfa_enabled")
        self.locale = data.get("locale")
        self.verified = data.get("verified")
        self.email = data.get("email")
        self.flags = UserFlags(data.get("flags", 0))
        self.premium_type = PremiumType(data["premium_type"]) if "premium_type" in data else None
        self.public_flags = UserFlags(data.get("public_flags", 0))

    def to_dict(self):
        return self._data

    @property
    def name(self):
        return self.username

    @property
    def avatar_url(self):
        return self.avatar_url_as()

    def avatar_url_as(self, fmt=None, static_fmt="webp"):
        if self.avatar is not None:
            if fmt is not None:
                return cdn_url(f"avatars/{self.id}/{self.avatar}.{fmt}")

            elif self.avatar.startswith("a_"):
                return cdn_url(f"avatars/{self.id}/{self.avatar}.gif")

            else:
                return cdn_url(f"avatars/{self.id}/{self.avatar}.{static_fmt}")

        else:
            return cdn_url(f"embed/avatars/{int(self.discriminator) % 5}.png")

    def __str__(self):
        return f"{self.name}#{self.discriminator}"


class Member(User):
    __slots__ = ("_data", "nick", "roles", "joined_at", "premium_since", "deaf", "mute", "permissions")

    def __init__(self, data):
        super().__init__(data["user"])
        self._data = data

        self.nick = data["nick"]
        self.roles = data["roles"]
        self.joined_at = parse_time(data["joined_at"])
        self.premium_since = parse_time(data.get("premium_since"))
        self.deaf = data.get("deaf", False)
        self.mute = data.get("mute", False)
        self.permissions = Permissions(int(data["permissions"])) if "permissions" in data else None

    def to_dict(self):
        return self._data

    @classmethod
    def from_message(cls, data):
        if "member" in data:
            return cls({
                "user": data["user"],
                **data["member"]
            })

        else:
            return User(data["author"])

    @classmethod
    def from_mention(cls, data):
        if "member" in data:
            return cls({
                **data.pop("member"),
                "user": data
            })

        else:
            return User(data)

    def __str__(self):
        return f"{self.name}#{self.discriminator}"


class MessageReaction:
    __slots__ = ("count", "me", "emoji")

    def __init__(self, data):
        self.count = data["count"]
        self.me = data["me"]
        self.emoji = data["emoji"]

    def to_dict(self):
        return {
            "count": self.count,
            "me": self.me,
            "emoji": self.emoji
        }


class MessageAttachment(Entity):
    __slots__ = ("filename", "size", "url", "proxy_url", "height", "width")

    def __init__(self, data):
        super().__init__()
        self.id = data["id"]
        self.filename = data["filename"]
        self.size = data["size"]
        self.url = data["url"]
        self.proxy_url = data["proxy_url"]
        self.height = data.get("height")
        self.width = data.get("width")

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "size": self.size,
            "url": self.url,
            "proxy_url": self.proxy_url,
            "height": self.height,
            "width": self.width
        }


class Message(Entity):
    __slots__ = ("_data", "channel_id", "guild_id", "author", "content", "timestamp", "edited_timestamp", "tts",
                 "mention_everyone", "mentions", "mention_roles", "attachments", "embeds", "reactions", "nonce",
                 "pinned", "webhook_id", "type", "flags")

    def __init__(self, data):
        super().__init__()
        self._data = data

        self.id = data["id"]
        self.channel_id = data["channel_id"]
        self.guild_id = data.get("guild_id")
        self.author = Member.from_message(data)
        self.content = data["content"]
        self.timestamp = parse_time(data["timestamp"])
        self.edited_timestamp = parse_time(data["edited_timestamp"])
        self.tts = data["tts"]
        self.mention_everyone = data["mention_everyone"]
        self.mentions = [Member.from_mention(m) for m in data["mentions"]]
        self.mention_roles = data["mention_roles"]
        self.attachments = [MessageAttachment(a) for a in data["attachments"]]
        self.embeds = data["embeds"]
        self.reactions = [MessageReaction(r) for r in data.get("reactions", [])]
        self.nonce = data.get("nonce")
        self.pinned = data["pinned"]
        self.webhook_id = data.get("webhook_id")
        self.type = MessageType(data["type"])
        self.flags = MessageFlags(data.get("flags", 0))

    def to_dict(self):
        return self._data


class Webhook(Entity):
    __slots__ = ("_data", "type", "guild_id", "channel_id", "user", "name", "avatar", "token", "application_id")

    def __init__(self, data):
        super().__init__()
        self._data = data

        self.id = data["id"]
        self.type = WebhookType(data["type"])
        self.guild_id = data.get("guild_id")
        self.channel_id = data.get("channel_id")
        self.user = User(data["user"]) if "user" in data else None
        self.name = data.get("name")
        self.avatar = data.get("avatar")
        self.token = data.get("token")
        self.application_id = data.get("application_id")

    @property
    def url(self):
        return "https://discord.com/api/v8/webhooks/{0.id}/{0.token}".format(self)

    def to_dict(self):
        return self._data
