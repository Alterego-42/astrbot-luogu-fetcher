from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict


@dataclass(slots=True)
class LuoguCommand:
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    precondition: str = ""
    postcondition: str = ""


class LuoguCommandBus:
    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[LuoguCommand], Awaitable[Any]]] = {}

    def register(self, command_name: str, handler: Callable[[LuoguCommand], Awaitable[Any]]) -> None:
        self._handlers[command_name] = handler

    async def execute(self, command: LuoguCommand) -> Any:
        handler = self._handlers.get(command.name)
        if handler is None:
            raise KeyError(f"Unhandled Luogu command: {command.name}")
        return await handler(command)
