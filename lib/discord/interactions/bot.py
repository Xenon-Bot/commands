import asyncio
import inspect
import sys
import traceback
from os import environ as env

import orjson
from aiohttp import web, ClientSession, TCPConnector
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from .command import *
from .component import *
from .context import *
from .modal import *
from .payloads import *
from .response import *
from ..http import *
from .state import *
from ..utils import *
from ...core import CoreClient

__all__ = (
    "InteractionBot",
)


class InteractionBot:
    def __init__(self, **kwargs):
        self.commands = []
        self.components = []
        self.modals = []
        self.public_key = VerifyKey(bytes.fromhex(kwargs["public_key"]))
        self.token = kwargs["token"]
        self.application_id = kwargs["application_id"]
        self._loop = None

        # Filled by setup()
        self.session = None
        self.http = None
        self.core = None

        self.modules = set()
        self.state = StateStore()

    @property
    def loop(self):
        return self._loop or asyncio.get_event_loop()

    def find_command(self, data):
        base_command = iterable_get(self.commands, name=data.name)
        if base_command is None:
            return None, None  # Out of sync; ignore

        for option in data.options:
            sub_command = iterable_get(base_command.sub_commands, name=option.name)
            if isinstance(sub_command, SubCommandGroup):
                for sub_option in option.options:
                    sub_sub_command = iterable_get(sub_command.sub_commands, name=sub_option.name)
                    if sub_sub_command is None:
                        return None, None  # Out of sync; ignore

                    return sub_sub_command, sub_option.options

            elif isinstance(sub_command, SubCommand):
                return sub_command, option.options

        return base_command, data.options

    def command(self, _callable=None, **kwargs):
        if _callable is None:
            def _predicate(_callable):
                cmd = make_command(Command, _callable, **kwargs)
                self.commands.append(cmd)
                return cmd

            return _predicate

        return make_command(Command, _callable, **kwargs)

    def component(self, _callable=None, **kwargs):
        if _callable is None:
            def _predicate(_callable):
                component = make_component(_callable, **kwargs)
                self.components.append(component)
                return component

            return _predicate

        component = make_component(_callable, **kwargs)
        self.components.append(component)
        return component

    def modal(self, _callable=None, **kwargs):
        if _callable is None:
            def _predicate(_callable):
                modal = make_modal(_callable, **kwargs)
                self.modals.append(modal)
                return modal

            return _predicate

        modal = make_modal(_callable, **kwargs)
        self.modals.append(modal)
        return modal

    def load_module(self, module):
        self.modules.add(module)
        for cmd in module.commands:
            self.commands.append(cmd)

        for c in module.components:
            self.components.append(c)

        for m in module.modals:
            self.modals.append(m)

    async def on_context_error(self, ctx, e):
        if isinstance(e, asyncio.CancelledError):
            raise e

        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        print("Command Error:\n", tb, file=sys.stderr)

    def _execute_command(self, command, payload, remaining_options):
        ctx = CommandContext(self, command, payload, args=remaining_options)

        try:
            values = {}
            for option in remaining_options:
                matching_option = iterable_get(command.options, name=option.name)
                if matching_option is not None:
                    value = matching_option.converter(option.value)
                    values[option.name] = value

            result = command.callable(ctx, **values)
            if inspect.isasyncgen(result):
                return result
            else:
                return result
        except Exception as e:
            return single_async_yield(self.on_context_error(ctx, e))

    async def _execute_command_autocomplete(self, command, payload, remaining_options):
        ctx = CommandAutocompleteContext(self, command, payload, args=remaining_options)

        for passed in remaining_options:
            if not passed.focused:
                continue

            for option in command.options:
                if option.name != passed.name:
                    continue

                if option.autocomplete:
                    yield await option.autocomplete(ctx, passed.value)

                break

        yield InteractionResponse.autocomplete()

    def _execute_component(self, component, payload, args):
        ctx = ComponentContext(self, component, payload)

        try:
            result = component.callable(ctx, *args)
            if inspect.isasyncgen(result):
                return result
            else:
                return single_async_yield(result)
        except Exception as e:
            return single_async_yield(self.on_context_error(ctx, e))

    async def _execute_modal(self, modal, payload):
        ctx = ModalContext(self, modal, payload)

        try:
            result = modal.callable(ctx)
            if inspect.isasyncgen(result):
                return result
            else:
                return single_async_yield(result)
        except Exception as e:
            return single_async_yield(self.on_context_error(ctx, e))

    async def _drive_executor(self, payload, executor):
        initial_response = self.loop.create_future()

        async def _predicate():
            # send values currently don't make it to the actual command handler
            next_send = None
            next_throw = None

            while True:
                try:
                    if next_throw is not None:
                        resp = await executor.athrow(next_throw)
                    else:
                        resp = await executor.asend(next_send)

                    if resp is None:
                        continue

                    next_send = None
                    next_throw = None
                    if initial_response.done():
                        try:
                            if resp.type == InteractionResponseType.CHANNEL_MESSAGE:
                                next_send = await self.http.create_interaction_response(
                                    payload.token,
                                    files=resp.files,
                                    **resp.data
                                )
                            elif resp.type == InteractionResponseType.UPDATE_MESSAGE:
                                next_send = await self.http.edit_interaction_response(
                                    payload.token,
                                    files=resp.files,
                                    **resp.data
                                )
                        except Exception as e:
                            next_throw = e
                    else:
                        initial_response.set_result(resp)
                except StopAsyncIteration:
                    break
            async for resp in executor:
                if initial_response.done():
                    try:
                        res = None
                        if resp.type == InteractionResponseType.CHANNEL_MESSAGE:
                            res = await self.http.create_interaction_response(payload.token, files=resp.files,
                                                                              **resp.data)
                        elif resp.type == InteractionResponseType.UPDATE_MESSAGE:
                            res = await self.http.edit_interactions_response(payload.token, files=resp.files,
                                                                             **resp.data)

                        await executor.asend(res)
                    except Exception as e:
                        try:
                            await executor.athrow(e)
                        except StopAsyncIteration:
                            pass
                else:
                    initial_response.set_result(resp)
                    try:
                        await executor.asend(None)
                    except StopAsyncIteration:
                        pass

        self.loop.create_task(_predicate())
        try:
            return await asyncio.wait_for(initial_response, timeout=2.5)
        except asyncio.TimeoutError:
            return InteractionResponse.message(
                "The command did not respond in time. This shouldn't happen :(",
                ephemeral=True
            )

    async def interaction_received(self, payload):
        if payload.type == InteractionType.PING:
            return InteractionResponse.pong()

        executor = None
        if payload.type == InteractionType.APPLICATION_COMMAND:
            command, remaining_options = self.find_command(payload.data)
            if command is None:
                return None

            executor = self._execute_command(command, payload, remaining_options)

        elif payload.type == InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE:
            command, remaining_options = self.find_command(payload.data)
            if command is None:
                return None

            executor = self._execute_command_autocomplete(command, payload, remaining_options)

        elif payload.type == InteractionType.APPLICATION_COMPONENT:
            parts = payload.data.custom_id.split("?")
            name = parts[0]
            if len(parts) == 1:
                args = []
            else:
                args = parts[1].split("&")

            for component in self.components:
                if component.name == name:
                    executor = self._execute_component(component, payload, args)
                    break

        elif payload.type == InteractionType.MODAL_SUBMIT:
            for modal in self.modals:
                if modal.name == payload.data.custom_id:
                    executor = self._execute_modal(modal, payload)
                    break

        if executor:
            return await self._drive_executor(payload, executor)

    async def aiohttp_entry(self, request):
        raw_data = await request.text()
        signature = request.headers.get("x-signature-ed25519")
        timestamp = request.headers.get("x-signature-timestamp")
        if signature is None or timestamp is None:
            return web.HTTPUnauthorized()

        try:
            self.public_key.verify(f"{timestamp}{raw_data}".encode(), bytes.fromhex(signature))
        except BadSignatureError:
            return web.HTTPUnauthorized()

        data = InteractionData(orjson.loads(raw_data))
        resp = await self.interaction_received(data)
        if resp is None:
            return web.json_response({}, status=400)

        return web.json_response(resp.to_dict())

    async def sanic_entry(self, request):
        from sanic import response

        raw_data = request.body.decode("utf-8")
        signature = request.headers.get("x-signature-ed25519")
        timestamp = request.headers.get("x-signature-timestamp")
        if signature is None or timestamp is None:
            return response.empty(status=401)

        try:
            self.public_key.verify(f"{timestamp}{raw_data}".encode(), bytes.fromhex(signature))
        except BadSignatureError:
            return response.empty(status=401)

        data = InteractionData(orjson.loads(raw_data))
        resp = await self.interaction_received(data)
        if resp is None:
            return response.json({}, status=400)

        return response.json(resp.to_dict())

    async def setup(self):
        bind_to = env.get("BIND_INTERFACE")
        if bind_to is not None:
            connector = TCPConnector(local_addr=(bind_to, 0))
        else:
            connector = TCPConnector()

        self.session = ClientSession(loop=self.loop, connector=connector)

        self._loop = asyncio.get_event_loop()
        self.http = HTTPClient(
            token=self.token,
            application_id=self.application_id,
            session=self.session
        )
        self.core = CoreClient(self.session, "http://127.0.0.1:8080/main", "1234567890")

        self.loop.create_task(self.state.expire_task())
        for module in self.modules:
            self.loop.create_task(module.post_setup())

    async def push_commands(self, guild_id=None):
        data = [c.to_payload() for c in self.commands if c.register]
        if guild_id is None:
            await self.http.replace_global_commands(data)

        else:
            await self.http.replace_guild_commands(guild_id, data)
