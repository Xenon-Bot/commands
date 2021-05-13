from dbots.cmd import *
from ecies.utils import generate_key
import base64
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import asyncio


def get_symmetric_key(key=None, nonce=None):
    key = key or get_random_bytes(16)
    nonce = nonce or get_random_bytes(16)
    return key, nonce, AES.new(key, mode=AES.MODE_GCM, nonce=nonce)


def key_to_id(key_bytes):
    return base64.b32encode(key_bytes).decode().rstrip("=")


def id_to_key(id_string):
    return base64.b32decode(id_string + "======")


async def get_public_key(bot, user_id):
    doc = await bot.db.encryption.find_one({"_id": user_id, "enabled": True})
    if doc is None:
        return None

    return doc["public_key"]


class EncryptionModule(Module):
    @Module.command()
    async def encryption(self):
        """
        Manage backup and chatlog encryption
        """

    @encryption.sub_command(visible=False, ephemeral=True)
    @checks.cooldown(1, 60, bucket=checks.CooldownType.AUTHOR)
    async def enable(self, ctx):
        """
        Enable encryption for new backups and chatlogs
        """
        result = await ctx.bot.db.encryption.update_one({"_id": ctx.author.id}, {"$set": {
            "enabled": True
        }})
        if result.matched_count > 0:
            await ctx.respond(**create_message(
                "**Encryption** for new backups and chatlogs has been **enabled** again. "
                "Your master key stays the same.",
                f=Format.SUCCESS
            ), ephemeral=True)
            return

        key = generate_key()
        private_key = key.secret
        public_key = key.public_key.format(False)
        await ctx.bot.db.encryption.update_one({"_id": ctx.author.id}, {"$set": {
            "_id": ctx.author.id,
            "enabled": True,
            "public_key": public_key
        }}, upsert=True)
        await ctx.respond(
            f"This is your **master key**. Please **store this key at a secure place** where only you can access it.\n"
            f"We **do not store this key** for you and are **not able to recover** "
            f"information if you happen to lose the key.\n\n"
            f"This key is required to retrieve a list of encrypted backups using `/backup list <master-key>`. "
            f"**There is no way to get a list of your encrypted backups if you lose this key**."
            f"```{base64.b32encode(private_key).decode().rstrip('=')}```",
            ephemeral=True
        )

    @encryption.sub_command(ephemeral=True)
    @checks.cooldown(1, 60, bucket=checks.CooldownType.AUTHOR)
    async def disable(self, ctx):
        """
        Disable encryption for new backups and chatlogs
        This will not reset your master key
        """
        result = await ctx.bot.db.encryption.update_one({"_id": ctx.author.id}, {"$set": {
            "enabled": False
        }})
        if result.matched_count == 0:
            await ctx.respond(**create_message(
                "Encryption was never enabled. Use `/encryption enable` to enable it.",
                f=Format.ERROR
            ), ephemeral=True)

        else:
            await ctx.respond(**create_message(
                "**Encryption** for new backups and chatlogs **has been disabled**. "
                "Use `/encryption enable` to enable it again.\n"
                "**This does not reset your master key**",
                f=Format.SUCCESS
            ), ephemeral=True)

    @encryption.sub_command(ephemeral=True)
    @checks.cooldown(1, 2 * 60, bucket=checks.CooldownType.AUTHOR, manual=True)
    async def reset(self, ctx):
        """
        Disable encryption, reset your master key and delete all existing encrypted backups
        """
        # Require a confirmation by the user
        await ctx.respond(**create_message(
            "**Hey, be careful!** This action will delete all you encrypted backups and **can not be undone**:\n\n"
            f"Type `/confirm` to confirm this action and continue.",
            f=Format.WARNING
        ), ephemeral=True)

        try:
            await self.bot.wait_for_confirmation(ctx, timeout=60)
        except asyncio.TimeoutError:
            await ctx.edit_response(**create_message(
                f"You action has **timed out**. Use `/encryption reset` to try again.",
                f=Format.INFO
            ), ephemeral=True)
            return

        await ctx.count_cooldown()
        await ctx.bot.db.backups.delete_many({"creator": ctx.author.id, "encrypted": True})
        await ctx.bot.db.encryption.delete_one({"_id": ctx.author.id})
        await ctx.edit_response(**create_message(
            "Encryption has been disabled, your master key has been reset and all your encrypted have been deleted.\n\n"
            "Use `/encryption enable` to enable encryption again and get a new master key.",
            f=Format.SUCCESS
        ), ephemeral=True)
