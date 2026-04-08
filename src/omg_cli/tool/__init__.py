from collections.abc import Awaitable, Callable
import inspect
from typing import Any, ClassVar, overload

from pydantic import BaseModel, create_model

from src.omg_cli.types.tool import Tool, ToolCallable

type ToolResult[T] = T | Awaitable[T]


class ToolManager:
    tools: ClassVar[dict[str, Tool[Any]]] = {}
    tag_index: ClassVar[dict[str, set[str]]] = {}

    @classmethod
    def register(cls, tool: Tool[Any]) -> Tool[Any]:
        existing_tool = cls.tools.get(tool.name)
        if existing_tool is not None:
            if (
                existing_tool._runner is None
                or tool._runner is None
                or existing_tool._runner.__qualname__ == tool._runner.__qualname__
            ):
                return existing_tool
            raise ValueError(f"Tool name conflict: {tool.name}")

        cls.tools[tool.name] = tool
        for tag in tool.tags:
            cls.tag_index.setdefault(tag, set()).add(tool.name)
        return tool

    @classmethod
    def get(cls, name: str) -> Tool[Any] | None:
        return cls.tools.get(name)

    @classmethod
    def list(cls, *, tags: str | list[str] | None = None) -> list[Tool[Any]]:
        if tags is None:
            return list(cls.tools.values())

        normalized_tags = _normalize_tags(tags)
        matching_names: set[str] | None = None
        for tag in normalized_tags:
            tag_names = cls.tag_index.get(tag, set())
            if matching_names is None:
                matching_names = set(tag_names)
            else:
                matching_names &= tag_names

        if not matching_names:
            return []

        return [cls.tools[name] for name in matching_names if name in cls.tools]

    @classmethod
    def clear(cls) -> None:
        cls.tools.clear()
        cls.tag_index.clear()


@overload
def register_tool[**P, T](
    func: ToolCallable[P, T],
    *,
    description: str | None = None,
    name: str | None = None,
    confirm: bool = False,
    tags: str | list[str] = "global",
) -> "Tool[T]": ...


@overload
def register_tool[**P, T](
    func: None = None,
    *,
    description: str | None = None,
    name: str | None = None,
    confirm: bool = False,
    tags: str | list[str] = "global",
) -> "Callable[[ToolCallable[P, T]], Tool[T]]": ...


def register_tool[**P, T](
    func: ToolCallable[P, T] | None = None,
    *,
    description: str | None = None,
    name: str | None = None,
    confirm: bool = False,
    tags: str | list[str] = "global",
) -> "Tool[T] | Callable[[ToolCallable[P, T]], Tool[T]]":
    """
    Decorator to register a function as a tool.

    Examples:
        @register_tool
        async def add(
            x: Annotated[int, Field(description="Left operand.")],
            y: Annotated[int, Field(description="Right operand.")],
        ) -> int:
            \"""Add two integers.\"""
            return x + y

        @register_tool(description="获取天气")
        async def get_weather(city: str) -> dict[str, str]:
            return {"city": city, "weather": "sunny"}
    """

    def decorator(tool_func: ToolCallable[P, T]) -> "Tool[T]":
        docstring = inspect.getdoc(tool_func) or ""
        tool_name = name or getattr(tool_func, "__name__", "tool")
        tool_description = (
            description or "\n".join([line.strip() for line in docstring.splitlines() if line.strip()]) or tool_name
        )
        tool = Tool(
            name=tool_name,
            description=tool_description,
            params_model=_build_tool_parameters(tool_func),
            confirm=confirm,
            tags=_normalize_tags(tags),
        )
        return ToolManager.register(tool.bind(tool_func))

    if func is None:
        return decorator

    return decorator(func)


def _build_tool_parameters[**P, T](tool_func: ToolCallable[P, T]) -> type[BaseModel]:
    signature = inspect.signature(tool_func)
    fields: dict[str, tuple[Any, Any]] = {}

    for parameter in signature.parameters.values():
        if parameter.kind not in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            raise TypeError(f"Unsupported parameter kind for tool {tool_func}: {parameter.kind}")

        annotation = Any if parameter.annotation is inspect.Signature.empty else parameter.annotation
        default = ... if parameter.default is inspect.Signature.empty else parameter.default
        fields[parameter.name] = (annotation, default)

    parameters_model = create_model(
        f"{getattr(tool_func, '__name__', 'Tool').title()}Parameters",
        **fields,  # type: ignore
    )

    return parameters_model


def _normalize_tags(tags: str | list[str] | None) -> frozenset[str]:
    if tags is None:
        return frozenset({"global"})

    values = [tags] if isinstance(tags, str) else tags
    normalized = {tag.strip() for tag in values if tag.strip()}
    normalized.add("global")
    return frozenset(normalized)
