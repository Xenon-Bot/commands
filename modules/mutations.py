import json
from datetime import datetime, timedelta

import grpc
from grpc.aio import AioRpcError
from xenon.mutations import service_pb2

from dbots import *
from dbots.cmd import *
from util import *

MUTATIONS_PER_PAGE = 10
MUTATION_TITLES = dict(
    guild_update="Server Updated",
    channel_update="Channel Updated",
    channel_delete="Channel Deleted",
    channel_create="Channel Created",
    thread_update="Thread Updated",
    thread_delete="Thread Deleted",
    thread_create="Thread Created",
    role_update="Role Updated",
    role_delete="Role Deleted",
    role_create="Role Created",
    bans_update="Ban Updated",
    emoji_create="Emoji Created",
    emoji_delete="Emoji Deleted",
    emoji_update="Emoji Updated",
    sticker_create="Sticker Created",
    sticker_delete="Sticker Deleted",
    sticker_update="Sticker Updated",
)


def get_mutation_title(mutation):
    return MUTATION_TITLES.get(mutation.kind, "Unknown Mutation Type")


def get_mutation_sub_title(mutation, data):
    if mutation.kind in {"channel_create", "channel_update", "thread_create", "thread_update"}:
        return f"<#{data['id']}>"
    if mutation.kind in {"role_create", "role_delete"}:
        return f"<@&{data['id']}>"

    return ""


def get_mutation_value_list(data, max_values=3):
    def display_value(key, value):
        # TODO: add special treatment for some keys (e.g. channel type)

        if value is None:
            return "None"
        elif isinstance(value, bool):
            return "Enabed" if value else "Disabled"
        elif isinstance(value, list):
            return f"{len(value)} items"
        elif isinstance(value, dict):
            if "new_value" in value:
                return display_value(key, value["new_value"])
            else:
                return f"{len(value)} items"

        value = str(value)
        if len(value) > 50:
            return f"{value[:50]} ..."

        return value

    values = [
        f"[2;31m{k.replace('_', ' ').title()}[0m: {display_value(k, v)}"
        for k, v in data.items()
    ]
    if len(values) > max_values:
        values = values[:max_values]
        values.append("[2;33m...[0m")

    result = "\n".join(values)
    return f"```ansi\n{result}\n```"


class MutationsModule(Module):
    @Module.command(default_member_permissions=Permissions.FlagList.administrator, dm_permission=False, beta=True)
    async def changes(self, ctx):
        """
        View and revert changes made to your Discord server
        """

    @changes.sub_command()
    @checks.guild_only
    @entitlement_required
    @checks.has_permissions_level()
    async def enable(self, ctx):
        """
        Enable change tracking for this server
        """
        await self.bot.rpc.mutations.EnableMutationTracking(service_pb2.EnableMutationTrackingRequest(
            guild_id=int(ctx.guild_id)
        ))
        await ctx.respond(**create_message(
            "**Change tracking has been enabled** for this server.\n\n"
            "You can view changes made to your server from now on with `/changes list`.",
            f=Format.SUCCESS
        ), ephemeral=True)

    @changes.sub_command()
    @checks.guild_only
    @entitlement_required
    @checks.has_permissions_level()
    async def disable(self, ctx):
        """
        Disable change logging for this server
        """
        await self.bot.rpc.mutations.DisableMutationTracking(service_pb2.DisableMutationTrackingRequest(
            guild_id=int(ctx.guild_id)
        ))
        await ctx.respond(**create_message(
            "**Change tracking has been disabled** for this server.",
            f=Format.SUCCESS
        ), ephemeral=True)

    async def _list_mutations(self, guild_id, start_timestamp, end_timestamp, skip=0):
        resp = await self.bot.rpc.mutations.ListMutations(service_pb2.ListMutationsRequest(
            guild_id=int(guild_id),
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        ))

        mutations = []
        for bucket in reversed(resp.buckets):
            for mutation in reversed(bucket.mutations):
                if skip > 0:
                    skip -= 1
                    continue

                if len(mutations) >= MUTATIONS_PER_PAGE:
                    break

                mutations.append((bucket, mutation))

        return list(reversed(mutations))

    async def _get_changes_list_page(self, guild_id, start_timestamp, end_timestamp, skip=0):
        mutations = await self._list_mutations(guild_id, start_timestamp, end_timestamp, skip)

        if len(mutations) == 0:
            return dict(
                **create_message(
                    "There **aren't any changes** yet.",
                    f=Format.INFO
                ),
                ephemeral=True
            )

        fields = []
        select_options = []
        for i, (bucket, mutation) in enumerate(mutations):
            mutation_id = f"{bucket.start_snapshot_id}_{mutation.hash}"
            data = json.loads(mutation.data)

            title = get_mutation_title(mutation)
            sub_title = get_mutation_sub_title(mutation, data)
            value_list = get_mutation_value_list(data)

            fields.append(dict(
                name=f"{i + 1}. {title}",
                value=f"{sub_title}\n{value_list}{'​' if i != len(mutations) - 1 else ''}",
            ))

            select_options.append(SelectMenuOption(
                label=f"{i + 1}. {title}",
                value=mutation_id
            ))

        if skip == 0:
            next_args = [str(end_timestamp), "", "0"]
        else:
            next_args = [str(start_timestamp), str(end_timestamp) if end_timestamp else "",
                         str(max(skip - MUTATIONS_PER_PAGE, 0))]

        if len(mutations) >= MUTATIONS_PER_PAGE:
            # We just assume there are more in the bucket
            previous_args = [str(start_timestamp), str(end_timestamp) if end_timestamp else "",
                             str(skip + MUTATIONS_PER_PAGE)]
        else:
            new_start_timestamp = datetime.fromtimestamp(start_timestamp) - timedelta(hours=6)
            previous_args = [str(int(new_start_timestamp.timestamp())), str(start_timestamp), "0"]

        return dict(
            embeds=[dict(
                title="Server Changes",
                fields=fields,
                color=Format.INFO.color,
                description=f"Displaying changes from **<t:{mutations[0][0].start_timestamp}>** until **<t:{mutations[-1][0].end_timestamp}>**.\n\n"
                            f"Select a change from below to get more information about it or revert it.\n​",
            )],
            components=[
                ActionRow(
                    SelectMenu(
                        *select_options,
                        max_values=1,
                        min_values=1,
                        custom_id="change_info",
                        placeholder="Select to revert"
                    )
                ),
                ActionRow(
                    Button(label="Previous Page", custom_id=f"change_list", args=previous_args),
                    Button(label="Next Page", custom_id=f"change_list", args=next_args,
                           disabled=end_timestamp is None and skip == 0)
                )
            ],
            ephemeral=True
        )

    @changes.sub_command()
    @checks.guild_only
    @entitlement_required
    @checks.has_permissions_level()
    async def list(self, ctx):
        """
        List changes that have recently been made to your server
        """
        ctx.defer(ephemeral=True)

        start_datetime = datetime.utcnow() - timedelta(hours=6)
        await ctx.respond(**await self._get_changes_list_page(ctx.guild_id, int(start_datetime.timestamp()), None))

    @Module.component(name="change_list")
    async def list_page(self, ctx, start_timestamp, end_timestamp, skip):
        ctx.defer()

        end_timestamp = int(end_timestamp) if end_timestamp else None
        data = await self._get_changes_list_page(ctx.guild_id, int(start_timestamp), end_timestamp, int(skip))
        await ctx.update(**data)

    @Module.component(name="change_info")
    async def info(self, ctx):
        mutation_id = ctx.values[0]
        start_snapshot_id, mutation_hash = mutation_id.split("_")

        try:
            resp = await self.bot.rpc.mutations.GetMutation(service_pb2.GetMutationRequest(
                guild_id=int(ctx.guild_id),
                start_snapshot_id=start_snapshot_id,
                mutation_hash=mutation_hash,
            ))
        except AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                await ctx.respond(**create_message(
                    "**Unknown change selected**. The change list is probably outdated, run `/changes list` again.",
                    f=Format.ERROR,
                ), ephemeral=True)
                return
            else:
                raise

        mutation = resp.mutation
        data = json.loads(mutation.data)

        description = f"{get_mutation_sub_title(mutation, data)}\n{get_mutation_value_list(data, 25)}"

        await ctx.respond(
            embeds=[dict(
                title=get_mutation_title(mutation),
                color=Format.INFO.color,
                description=f"{description}\n\n *Click `Revert Change` to revert this change or "
                            f"`Revert All After This` to revert this change and all changes that happened after it.*"
            )],
            components=[
                ActionRow(
                    Button(style=ButtonStyle.PRIMARY, label="Revert Change", custom_id=f"revert_preview",
                           args=["one", mutation_id]),
                    # Button(style=ButtonStyle.SECONDARY, label="Revert All After This", custom_id=f"revert_preview",
                    #        args=["until", mutation_id])
                )
            ],
            ephemeral=True
        )

    @Module.component(name="change_revert_preview")
    async def revert_preview(self, ctx, mode, mutation_hash):
        pass

    @Module.component(name="change_revert")
    @entitlement_required
    @checks.has_permissions_level(destructive=True)
    @checks.bot_has_permissions("administrator")
    async def revert(self, ctx, mode, mutation_hash):
        pass
