from collections.abc import Sequence
from datetime import UTC, datetime
import json
from typing import Any, Literal, ParamSpec, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from omg_cli.types.constants import STOP_REASON_ALIASES, StopReason

type Role = Literal[
    "system",
    "developer",
    "user",
    "assistant",
    "tool",
]

P = ParamSpec("P")
T = TypeVar("T")


class TextSegment(BaseModel):
    type: Literal["text"] = "text"
    text: str

    def __str__(self) -> str:
        return self.text

    def to_user_message(self) -> "Message":
        return Message(role="user", content=[self])


class ImageSegment(BaseModel):
    type: Literal["image"] = "image"
    url: str

    def __str__(self) -> str:
        return f"[Image: {self.url}]"


class ThinkSegment(BaseModel):
    type: Literal["think"] = "think"
    thought_process: str
    signature: str | None = None  # Anthropic thinking signature for verification

    def __str__(self) -> str:
        return f"[Thinking: {self.thought_process[:200]}...]"


class ToolSegment(BaseModel):
    type: Literal["tool"] = "tool"
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"[Tool call: {self.tool_name}]"

    def to_tool_call(self) -> "ToolCall":
        return ToolCall(
            type="function",
            id=self.tool_call_id,
            function=ToolCallFunctionBody(name=self.tool_name, arguments=self.arguments or {}),
        )


class ToolResultSegment(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    tool_name: str
    content: Any

    is_error: bool = False

    def __str__(self) -> str:
        content_str = str(self.content)
        if len(content_str) > 100:
            content_str = content_str[:100] + "..."
        return f"[Tool result: {self.tool_name} = {content_str}]"


class ToolCallFunctionBody(BaseModel):
    name: str
    arguments: dict[str, Any]


class ToolCall(BaseModel):
    type: Literal["function"] = "function"
    id: str

    function: ToolCallFunctionBody


class TextDetailSegment(BaseModel):
    type: Literal["text_detail"] = "text_detail"
    text: str
    index: int


class ThinkDetailSegment(BaseModel):
    type: Literal["think_detail"] = "think_detail"
    thought_process: str
    index: int


class ToolCallDetailSegment(BaseModel):
    type: Literal["tool_call_detail"] = "tool_call_detail"
    tool_call_id: str
    tool_name: str
    partial_arguments: str = ""
    arguments: dict[str, Any] | None = None
    index: int

    def check_complete(self) -> bool:
        try:
            json.dumps(self.arguments)
            return True
        except TypeError, ValueError:
            return False


class StopSegment(BaseModel):
    type: Literal["stop"] = "stop"
    reason: StopReason

    @classmethod
    def from_raw_reason(cls, reason: str) -> "StopSegment":
        return cls.model_validate({"reason": reason})

    @field_validator("reason", mode="before", check_fields=False)
    def validate_reason(cls, v: str | StopReason) -> StopReason:
        if isinstance(v, str):
            return STOP_REASON_ALIASES.get(v.strip().lower(), "other")
        return v


class UsageSegment(BaseModel):
    type: Literal["usage"] = "usage"
    input_tokens: int
    output_tokens: int
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None

    @field_validator("total_tokens", mode="before", check_fields=False)
    def compute_total_tokens(cls, v, values):
        if v is not None:
            return v

        input_tokens = values.get("input_tokens", 0)
        output_tokens = values.get("output_tokens", 0)
        return input_tokens + output_tokens


MessageSegment = TextSegment | ImageSegment | ThinkSegment | ToolSegment | ToolResultSegment
MessageDetailSegment = TextDetailSegment | ThinkDetailSegment | ToolCallDetailSegment | UsageSegment
MessageCompleteSegment = MessageSegment | StopSegment | UsageSegment
MessageStreamSegment = MessageDetailSegment | MessageCompleteSegment

SegmentType = Literal["text", "think", "tool", "refusal", "stop"]


class Message(BaseModel):
    role: Role

    # The name of the user or sy stem sending the message
    name: str | None = None

    content: Sequence[MessageSegment]

    tool_calls: list[ToolCall] = Field(default_factory=list)

    time: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    input_tokens: int | None = None
    output_tokens: int | None = None

    # Allow additional arbitrary fields
    model_config = ConfigDict(extra="allow")

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.content if isinstance(segment, TextSegment))

    @property
    def thinking(self) -> str:
        return "".join(segment.thought_process for segment in self.content if isinstance(segment, ThinkSegment))

    @property
    def in_thinking(self) -> bool:
        return any(isinstance(segment, ThinkDetailSegment | ThinkSegment) for segment in self.content) and not any(
            isinstance(segment, TextDetailSegment | TextSegment) for segment in self.content
        )

    def __model_post_init__(self):
        # In the user message containing tool results,
        # the tool_result blocks must come FIRST in the content array.
        # Any text must come AFTER all tool results.
        self.content = sorted(self.content, key=lambda seg: isinstance(seg, ToolResultSegment), reverse=True)


class MessageStreamDeltaEvent(BaseModel):
    event: Literal["delta"] = "delta"
    segment: MessageDetailSegment
    index: int


class MessageStreamCompleteEvent(BaseModel):
    event: Literal["complete"] = "complete"
    segment: MessageCompleteSegment
    index: int

    def to_message(self, role: Role = "assistant") -> Message:
        if isinstance(self.segment, StopSegment):
            raise ValueError("Stop segments cannot be converted to messages")
        elif isinstance(self.segment, UsageSegment):
            raise ValueError("Usage segments cannot be converted to messages")

        return Message(role=role, content=[self.segment])

    @property
    def stop_reason(self) -> StopReason:
        if isinstance(self.segment, StopSegment):
            return self.segment.reason
        raise ValueError("Only stop segments have stop reasons")


type MessageStreamEvent = MessageStreamDeltaEvent | MessageStreamCompleteEvent
