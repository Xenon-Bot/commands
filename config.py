from os import environ as env

PUBLIC_KEY = public_key = env.get("PUBLIC_KEY")
GUILD_ID = env.get("GUILD_ID")

MONGO_URL = env.get("MONGO_URL", "mongodb://localhost")
REDIS_URL = env.get("REDIS_URL", "redis://localhost")

BACKUPS_SERVICES = env.get("BACKUPS_SERVICE", "127.0.0.1:8081")
MUTATIONS_SERVICE = env.get("MUTATIONS_SERVICE", "127.0.0.1:8082")

_host = env.get("HOST", "127.0.0.1:8080").split(":")

HOST = _host[0]
PORT = int(_host[1])
