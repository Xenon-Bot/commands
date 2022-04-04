from abc import ABC


__all__ = (
    "Flags",
    "SystemChannelFlags",
    "UserFlags",
    "MessageFlags",
    "Permissions",
    "PermissionOverwrites"
)


class Flags(ABC):
    class FlagList:
        @classmethod
        def collect_flags(cls):
            return {
                name: value
                for name, value in cls.__dict__.items()
                if isinstance(value, int)
            }

        @classmethod
        def max_value(cls):
            max_bits = max(cls.collect_flags().values()).bit_length()
            return (2 ** max_bits) - 1

    DEFAULT_VALUE = 0
    FLAGS = FlagList.collect_flags()

    def __init__(self, value=None, **kwargs):
        self.value = value or self.DEFAULT_VALUE
        for key, value in kwargs.items():
            flag = self.FLAGS.get(key)
            if flag is None:
                raise TypeError(f"{key} is not a valid flag name.")

            self._set_flag(flag, value)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.value == other.value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.value)

    def __int__(self):
        return int(self.value)

    def __getattr__(self, item):
        flag = self.FLAGS.get(item)
        if flag is not None:
            return self._has_flag(flag)

        raise AttributeError

    def __setattr__(self, key, value):
        flag = self.FLAGS.get(key)
        if flag is not None:
            return self._set_flag(flag, value)

        return super().__setattr__(key, value)

    def __iter__(self):
        for name, flag in self.FLAGS.items():
            yield name, self._has_flag(flag)

    def _set_flag(self, flag, value):
        if value:
            self.value |= flag

        else:
            self.value &= ~flag

    def _has_flag(self, flag):
        return (self.value & flag) == flag

    def update(self, **kwargs):
        for key, value in kwargs.items():
            flag = self.FLAGS.get(key)
            if flag is None:
                raise TypeError(f"{key} is not a valid flag name.")

            self._set_flag(flag, value)

    def reset(self):
        self.value = self.DEFAULT_VALUE


class SystemChannelFlags(Flags):
    class FlagList(Flags.FlagList):
        suppress_join_notifications = 1 << 0
        suppress_premium_subscriptions = 1 << 1

    DEFAULT_VALUE = 0
    FLAGS = FlagList.collect_flags()


class UserFlags(Flags):
    class FlagList(Flags.FlagList):
        discord_employee = 1 << 0
        discord_partner = 1 << 1
        hypesquad_events = 1 << 2
        bug_hunter_level_1 = 1 << 3
        house_bravery = 1 << 6
        house_brilliance = 1 << 7
        house_balance = 1 << 8
        early_supporter = 1 << 9
        team_user = 1 << 10
        system = 1 << 12
        bug_hunter_level_2 = 1 << 14
        verified_bot = 1 << 16
        verified_bot_developer = 1 << 17

    DEFAULT_VALUE = 0
    FLAGS = FlagList.collect_flags()


class MessageFlags(Flags):
    class FlagList(Flags.FlagList):
        crossposted = 1 << 0
        is_crossposted = 1 << 1
        suppress_embeds = 1 << 2
        source_message_deleted = 1 << 3
        urgent = 1 << 4

    DEFAULT_VALUE = 0
    FLAGS = FlagList.collect_flags()


class Permissions(Flags):
    class FlagList(Flags.FlagList):
        create_instant_invite = 1 << 0
        kick_members = 1 << 1
        ban_members = 1 << 2
        administrator = 1 << 3
        manage_channels = 1 << 4
        manage_guild = 1 << 5
        add_reactions = 1 << 6
        view_audit_log = 1 << 7
        priority_speaker = 1 << 8
        stream = 1 << 9
        read_messages = 1 << 10
        send_messages = 1 << 11
        send_tts_messages = 1 << 12
        manage_messages = 1 << 13
        embed_links = 1 << 14
        attach_files = 1 << 15
        read_message_history = 1 << 16
        mention_everyone = 1 << 17
        external_emojis = 1 << 18
        view_guild_insights = 1 << 19
        connect = 1 << 20
        speak = 1 << 21
        mute_members = 1 << 22
        deafen_members = 1 << 23
        move_members = 1 << 24
        use_voice_activation = 1 << 25
        change_nickname = 1 << 26
        manage_nicknames = 1 << 27
        manage_roles = 1 << 28
        manage_webhooks = 1 << 29
        manage_emojis = 1 << 30

    DEFAULT_VALUE = 0
    FLAGS = FlagList.collect_flags()

    def __le__(self, other):
        return (self.value & other.value) == self.value

    def __ge__(self, other):
        return (self.value | other.value) == self.value

    def __lt__(self, other):
        return self.is_subset(other) and self != other

    def __gt__(self, other):
        return self.is_superset(other) and self != other

    @classmethod
    def none(cls):
        return cls(0)

    @classmethod
    def all(cls):
        return cls(cls.FlagList.max_value())


class PermissionOverwrites:
    VALID_FLAGS = Permissions.FLAGS.keys()

    def __init__(self, **kwargs):
        self._values = {}
        for key, value in kwargs.items():
            if key in self.VALID_FLAGS:
                self._values[key] = value

    def __setattr__(self, key, value):
        if key in self.VALID_FLAGS:
            self._values[key] = value

        return super().__setattr__(key, value)

    @classmethod
    def from_pair(cls, allow, deny):
        result = cls()
        for key, value in allow:
            if value is True:
                setattr(result, key, True)

        for key, value in deny:
            if value is True:
                setattr(result, key, False)

        return result

    def pair(self):
        allow = Permissions.none()
        deny = Permissions.none()

        for key, value in self._values.items():
            if value is True:
                setattr(allow, key, True)

            elif value is False:
                setattr(deny, key, True)

        return allow, deny

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)