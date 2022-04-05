import asyncio
from os import environ as env
from aiohttp import web
from concurrent.futures import ThreadPoolExecutor
from lib.discord import *

from bot import Xenon
from modules import backups

Format.ERROR.components = [ActionRow(
    Button(label="Wiki", url="https://wiki.xenon.bot", emoji="📚"),
    Button(label="Support", url="https://xenon.bot/discord", emoji="❔")
)]

bot = Xenon(
    public_key=env["PUBLIC_KEY"],
    token=env["TOKEN"],
    application_id=env["APPLICATION_ID"]
)
modules = {
    backups.BackupsModule
}
for module in modules:
    bot.load_module(module(bot))

app = web.Application()


@app.on_startup.append
async def prepare_bot(*_):
    await bot.setup()
    # await bot.http.replace_guild_commands(bot.guild_id, [])
    # await bot.http.replace_global_commands([])
    # await bot.push_commands(guild_id=env.get("GUILD_ID"))


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=10))
    app.add_routes([web.post("/gateway", bot.aiohttp_entry)])
    host = env.get("HOST", "127.0.0.1:8787").split(":")
    web.run_app(app, host=host[0], port=int(host[1]))
