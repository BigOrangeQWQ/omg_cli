from collections.abc import Awaitable, Callable
import inspect
from typing import Any

from pydantic import BaseModel, ConfigDict, PrivateAttr, computed_field
from pydantic.json_schema import GenerateJsonSchema

type ToolResult[T] = T | Awaitable[T]
type ToolCallable[**P, T] = Callable[P, ToolResult[T]]


class ToolError(Exception):
    """Exception raised when a tool execution fails.

    The error message will be returned to the LLM as the tool result.
    """

    pass


class ToolJsonSchemaGenerator(GenerateJsonSchema):
    def field_title_should_be_set(self, schema) -> bool:
        return False


class Tool[T](BaseModel):
    name: str
    description: str
    params_model: type[BaseModel] | None = None
    confirm: bool = False
    tags: frozenset[str] = frozenset({"global"})

    # Private storage for direct parameters schema (used by MCP tools)
    _parameters_schema: dict[str, Any] | None = PrivateAttr(default=None)
    _runner: ToolCallable[..., T] | None = PrivateAttr(default=None)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def model_post_init(self, context: Any) -> None:
        """Validate that either params_model or _parameters_schema is provided."""
        if self.params_model is None and self._parameters_schema is None:
            raise ValueError("Either params_model or parameters schema must be provided")
        if self.params_model is not None and self._parameters_schema is not None:
            raise ValueError("Cannot provide both params_model and parameters schema")

    @classmethod
    def from_parameters(
        cls,
        name: str,
        description: str,
        parameters: dict[str, Any],
        confirm: bool = False,
        tags: frozenset[str] = frozenset({"global"}),
    ) -> "Tool":
        """Create a Tool directly from parameters schema (e.g., MCP tools)."""

        # Create a dummy params_model to satisfy Pydantic validation
        class DummyModel(BaseModel):
            pass

        instance = cls(
            name=name,
            description=description,
            params_model=DummyModel,  # Temporary, will be ignored
            confirm=confirm,
            tags=tags,
        )
        instance.params_model = None  # Clear it
        instance._parameters_schema = parameters
        return instance

    def bind[**P](self, runner: ToolCallable[P, T]) -> "Tool[T]":
        self._runner = runner
        return self

    async def __call__(self, **kwargs: Any) -> T:
        if self._runner is None:
            raise NotImplementedError("Tool cannot be called directly")

        try:
            tool_result = self._runner(**kwargs)
            if inspect.isawaitable(tool_result):
                return await tool_result
            return tool_result
        except ToolError:
            # Re-raise ToolError as-is
            raise
        except Exception as e:
            # Wrap other exceptions in ToolError
            raise ToolError(f"Tool execution failed: {e}") from e

    @computed_field
    @property
    def parameters(self) -> dict[str, Any]:
        """Get parameters schema from either params_model or _parameters_schema."""
        if self._parameters_schema is not None:
            return self._parameters_schema

        # Generate from params_model
        if self.params_model is None:
            raise ValueError("Tool has neither params_model nor parameters schema")

        schema: dict[str, Any] = self.params_model.model_json_schema(schema_generator=ToolJsonSchemaGenerator)
        schema["additionalProperties"] = False
        if "title" in schema:
            schema.pop("title")
        return schema
