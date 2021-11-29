import asyncio
import json

from dbots.cmd import *
from dbots import *
from dbots.protos.isolator import service_pb2 as isolator_pb2

SCRIPT_WRAPPER = """
((window) => {
    const data = {DATA};
    
    const container = new GuildContainer(data);
    window.guild = container;
    window.server = container;
})(globalThis);

{SCRIPT}

__applyMutations(guild);
"""


def mutation_list(mutations):
    def count_by_type(_type):
        return len([m for m in mutations if m["kind"] == _type])

    return f"- {count_by_type(MutationType.CHANNEL_CREATE)} Channels will be created\n" \
           f"- {count_by_type(MutationType.CHANNEL_UPDATE)} Channels will be updated\n" \
           f"- {count_by_type(MutationType.CHANNEL_DELETE)} Channels will be deleted\n" \
           f"- {count_by_type(MutationType.ROLE_CREATE)} Roles will be created\n" \
           f"- {count_by_type(MutationType.ROLE_UPDATE)} Roles will be updated\n" \
           f"- {count_by_type(MutationType.ROLE_DELETE)} Roles will be deleted\n"


class MutationsModule(Module):
    @Module.command()
    async def mutate(self, ctx):
        """
        Apply mutation actions to your server and its channels and roles
        """

    @mutate.sub_command()
    @checks.guild_only
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    @checks.cooldown(1, 30, bucket=checks.CooldownType.GUILD, manual=True)
    async def script(self, ctx):
        """
        Run a mutation script on this server
        """
        await ctx.modal(
            custom_id="mutate_script_submit",
            title="Your Script",
            components=[
                ActionRow(TextInput(
                    style=TextInputStyle.PARAGRAPH,
                    custom_id="script",
                    label="Mutation Script",
                    placeholder="guild.getChannels().forEach(c => guild.editChannel(c.id, {name: 'wtf'}))"
                ))
            ]
        )

    @Module.modal(name="mutate_script_submit")
    async def script_submit(self, ctx):
        script = None
        for row in ctx.components:
            for component in row.components:
                if component.custom_id == "script":
                    script = component.value
                    break
            if script:
                break
        else:
            await ctx.respond(**create_message(
                f"Something went wrong while trying to process your response, please try again later.",
                f=Format.ERROR
            ), ephemeral=True)
            return

        roles = await ctx.fetch_guild_roles()
        channels = await ctx.fetch_guild_channels()

        serialized_data = json.dumps({
            "roles": [r.to_dict() for r in roles],
            "channels": [c.to_dict() for c in channels]
        })
        wrapped_script = SCRIPT_WRAPPER.replace("{SCRIPT}", script).replace("{DATA}", serialized_data)

        async def _schedule_script(_stream):
            await _stream.send_message(isolator_pb2.IsolateRequest(
                initialize_message=isolator_pb2.InitializeIsolateMessage(
                    cpu_time_limit=10,
                    execution_time_limit=25,
                    resource_requests_limit=1
                )
            ))

            await _stream.send_message(isolator_pb2.IsolateRequest(
                script_schedule_message=isolator_pb2.ScheduleIsolateScriptMessage(
                    kind=isolator_pb2.ScheduleIsolateScriptMessage.ScriptKind.DEFAULT,
                    content=wrapped_script
                )
            ))

        async with ctx.bot.rpc.isolator.AcquireIsolate.open() as stream:
            await stream.send_request()
            self.bot.loop.create_task(_schedule_script(stream))

            try:
                while True:
                    resp = await asyncio.wait_for(stream.recv_message(), timeout=1)
                    if resp.HasField("script_resource_request"):
                        msg = resp.script_resource_request
                        if msg.kind == "apply_mutations":
                            mutations = json.loads(msg.payload)
                            break

                        if msg.kind == "console":
                            print(msg.payload.decode("utf-8"))

                    elif resp.HasField("script_done_message"):
                        msg = resp.script_done_message
                        if msg.HasField("error"):
                            await ctx.respond(**create_message(
                                f"There was an error in your script: ```js\n{msg.error.text}\n```",
                                f=Format.ERROR
                            ), ephemeral=True)
                            return

            except asyncio.TimeoutError:
                await ctx.respond(**create_message(
                    f"Something went wrong while trying to execute your script, please try again later.",
                    f=Format.ERROR
                ), ephemeral=True)
                return
            finally:
                await stream.end()

        redis_key = f"mutate_script:{unique_id()}"
        await ctx.bot.redis.setex(redis_key, 60 * 5, json.dumps({
            "mutations": mutations
        }))

        await ctx.respond(
            **create_message(
                "**Hey, be careful!** The following actions will be taken on this server and **can not be undone**:\n\n"
                f"{mutation_list(mutations)}",
                f=Format.WARNING
            ),
            components=[
                ActionRow(
                    Button(label="Confirm", style=ButtonStyle.SUCCESS, custom_id=f"mutate_script_confirm",
                           args=[redis_key]),
                    Button(label="Cancel", style=ButtonStyle.DANGER, custom_id=f"mutate_script_cancel",
                           args=[redis_key])
                )
            ],
            ephemeral=True
        )

    @Module.component(name="mutate_script_confirm")
    async def script_confirm(self, ctx, redis_key):
        pass

    @Module.component(name="mutate_script_cancel")
    async def script_cancel(self, ctx, redis_key):
        await ctx.bot.redis.delete(redis_key)
        await ctx.update(**create_message(
            "The mutation process has been **cancelled**.\n\n"
            "Use `/mutate script` to try again.",
            f=Format.INFO
        ), ephemeral=True)
