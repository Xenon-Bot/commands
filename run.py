import asyncio
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

import config
from bot import Xenon
from dbots.cmd import *
from modules import backups, basics, settings, audit_logs, templates, premium, clone, export, mutations

Format.ERROR.components = [ActionRow(
    Button(label="Wiki", url="https://wiki.xenon.bot", emoji="📚"),
    Button(label="Support", url="https://xenon.bot/discord", emoji="❔")
)]

bot = Xenon(
    public_key=config.PUBLIC_KEY,
    guild_id=config.GUILD_ID,
    beta_guild_id=config.BETA_GUILD_ID,
)
modules = {
    backups.BackupsModule,
    basics.BasicsModule,
    settings.SettingsModule,
    audit_logs.AuditLogModule,
    templates.TemplatesModule,
    premium.PremiumModule,
    clone.CloneModule,
    export.ExportModule,
    mutations.MutationsModule
}
for module in modules:
    bot.load_module(module(bot))

app = web.Application()


@app.on_startup.append
async def prepare_bot(*_):
    await bot.setup(config.REDIS_URL)
    # await bot.http.replace_guild_commands(bot.guild_id, [])
    # await bot.http.replace_global_commands([])
    # await bot.push_commands()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=10))
    app.add_routes([web.post("/entry", bot.aiohttp_entry)])
    web.run_app(app, host=config.HOST, port=config.PORT)
