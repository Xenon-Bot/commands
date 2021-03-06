import asyncio
from os import environ as env
from aiohttp import web
from concurrent.futures import ThreadPoolExecutor
import sentry_sdk
from dbots.cmd import *

from bot import Xenon
from modules import backups, basics, settings, audit_logs, templates, premium, admin, clone, encryption

if env.get("SENTRY"):
    sentry_sdk.init(
        env["SENTRY"],
        traces_sample_rate=0.1
    )

Format.ERROR.components = [ActionRow(
    Button(label="Wiki", url="https://wiki.xenon.bot", emoji="📚"),
    Button(label="Support", url="https://xenon.bot/discord", emoji="❔")
)]

bot = Xenon(
    public_key=env.get("PUBLIC_KEY"),
    token=env.get("TOKEN"),
    guild_id=env.get("GUILD_ID")
)
modules = {
    backups.BackupsModule,
    basics.BasicsModule,
    settings.SettingsModule,
    audit_logs.AuditLogModule,
    templates.TemplatesModule,
    premium.PremiumModule,
    admin.AdminModule,
    clone.CloneModule,
    # encryption.EncryptionModule
}
for module in modules:
    bot.load_module(module(bot))

app = web.Application()


@app.on_startup.append
async def prepare_bot(*_):
    await bot.setup(env.get("REDIS_URL", "redis://localhost"))
    # await bot.http.replace_guild_commands(bot.guild_id, [])
    # await bot.http.replace_global_commands([])
    # await bot.push_commands()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=10))
    app.add_routes([web.post("/entry", bot.aiohttp_entry)])
    web.run_app(app, host=env.get("HOST", "127.0.0.1"), port=env.get("PORT"))
