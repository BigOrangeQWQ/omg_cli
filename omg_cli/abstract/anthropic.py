from collections.abc import AsyncIterator
from functools import cache
from typing import Any, override

from anthropic import AsyncAnthropic
from anthropic.types import (
    InputJSONDelta,
    MessageDeltaUsage,
    MessageParam,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
    RawMessageDeltaEvent,
    RawMessageStartEvent,
    RawMessageStopEvent,
    SignatureDelta,
    TextBlock,
    TextBlockParam,
    TextDelta,
    ThinkingBlock,
    ThinkingBlockParam,
    ThinkingDelta,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlock,
    ToolUseBlockParam,
)

from omg_cli.abstract import ChatAdapter
from omg_cli.abstract.utils import Messages, to_messages
from omg_cli.types.message import (
    Message,
    MessageStreamCompleteEvent,
    MessageStreamDeltaEvent,
    MessageStreamEvent,
    StopSegment,
    TextDetailSegment,
    TextSegment,
    ThinkDetailSegment,
    ThinkSegment,
    ToolCall,
    ToolCallDetailSegment,
    ToolCallFunctionBody,
    ToolResultSegment,
    ToolSegment,
    UsageSegment,
)
from omg_cli.types.skill import SkillRef, normalize_skill_id
from omg_cli.types.tool import Tool


class AnthropicAPI(ChatAdapter):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.anthropic.com",
        stream: bool = False,
        timeout: int = 60,
        thiking_supported: bool = True,
        skills: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key, model, base_url, stream, **kwargs)
        self.client = AsyncAnthropic(api_key=self.api_key, base_url=self.base_url, timeout=timeout)
        self._thinking_supported = thiking_supported
        self._skills: list[SkillRef] = [normalize_skill_id(s) for s in (skills or [])]

    @property
    def type(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def thinking_supported(self) -> bool:
        return self._thinking_supported

    @cache
    @override
    async def list_models(self) -> list[str]:
        models = await self.client.models.list()
        model_names = []
        async for model in models:
            model_names.append(model.id)
        return model_names

    @override
    async def context_length(self) -> int:
        """Get the model's context window length in tokens.

        Uses a mapping table since Anthropic's API doesn't expose max_context_length.
        Default to 150k tokens if model is unknown or API call fails.
        """
        if self.max_input_tokens:
            return self.max_input_tokens
        try:
            model = await self.client.models.retrieve(self.model)
            return model.max_input_tokens or 150000
        except Exception:
            # API may not support models.retrieve, return default
            return 150000

    def _build_request_kwargs(
        self,
        system_prompt: str,
        messages: Messages,
        tools: list[Tool],
        max_tokens: int | None = None,
        thinking: bool = False,
        skills: list[SkillRef] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        anthropic_messages: list[MessageParam] = []
        for message in to_messages(messages):
            anthropic_messages.extend(message_to_anthropic(message))

        request_kwargs = dict(kwargs)
        request_kwargs.pop("stream", None)

        # Merge runtime skills with instance-level skills
        active_skills = list(self._skills)
        if skills:
            active_skills.extend(skills)
        # Deduplicate by skill_id
        seen: set[str] = set()
        deduped_skills: list[SkillRef] = []
        for s in active_skills:
            if s.skill_id not in seen:
                seen.add(s.skill_id)
                deduped_skills.append(s)

        anthropic_tools = [tool_call_to_anthropic_tool_use(tool) for tool in tools]

        # Skills require code_execution tool
        if deduped_skills:
            has_code_execution = any(t.get("type") == "code_execution" for t in anthropic_tools)  # type: ignore
            if not has_code_execution:
                anthropic_tools.insert(0, {"type": "code_execution"})  # type: ignore

        request_kwargs.update(
            {
                "model": self.model,
                "messages": anthropic_messages,
                "system": system_prompt,
                "tools": anthropic_tools,
                "max_tokens": max_tokens if max_tokens is not None else 8192,
            }
        )

        # Add thinking configuration if enabled
        if thinking and self._thinking_supported:
            # Calculate budget_tokens: must be >= 1024 and less than max_tokens
            # Use 1/3 of max_tokens as default budget, clamped to valid range
            max_tok = request_kwargs["max_tokens"]
            budget_tokens = min(max(max_tok // 3, 1024), max_tok - 1)
            request_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget_tokens,
            }

        # Inject skills via extra_body / extra_headers (SDK 0.86.0 does not natively support container dict)
        if deduped_skills:
            extra_body = request_kwargs.get("extra_body") or {}
            if not isinstance(extra_body, dict):
                extra_body = {}
            extra_body["container"] = {
                "skills": [s.model_dump() for s in deduped_skills],
            }
            request_kwargs["extra_body"] = extra_body

            extra_headers = request_kwargs.get("extra_headers") or {}
            if not isinstance(extra_headers, dict):
                extra_headers = {}
            existing_betas = extra_headers.get("anthropic-beta", "")
            required_betas = ["code-execution-2025-08-25", "skills-2025-10-02"]
            existing_list = [b.strip() for b in existing_betas.split(",") if b.strip()]
            for b in required_betas:
                if b not in existing_list:
                    existing_list.append(b)
            extra_headers["anthropic-beta"] = ", ".join(existing_list)
            request_kwargs["extra_headers"] = extra_headers

        return request_kwargs

    def _get_segment_index(
        self,
        segment_indexes: dict[tuple[str, int], int],
        *,
        segment_type: str,
        block_index: int,
    ) -> int:
        key = (segment_type, block_index)
        if key not in segment_indexes:
            segment_indexes[key] = len(segment_indexes)
        return segment_indexes[key]

    async def chat(
        self,
        system_prompt: str,
        messages: Messages,
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Message:
        if kwargs.get("stream", False):
            raise NotImplementedError("Streaming is not supported in chat method. Use stream method instead.")
        if tools is None:
            tools = []

        resp = await self.client.messages.create(
            **self._build_request_kwargs(system_prompt, messages, tools, max_tokens=max_tokens, **kwargs)
        )
        message_segments = []
        tool_calls = []

        for part in resp.content:
            if isinstance(part, TextBlock):
                message_segments.append(TextSegment(text=part.text))
            if isinstance(part, ToolUseBlock):
                message_segments.append(
                    ToolSegment(
                        tool_call_id=part.id,
                        tool_name=part.name,
                    )
                )
                tool_calls.append(
                    ToolCall(
                        type="function",
                        id=part.id,
                        function=ToolCallFunctionBody(
                            name=part.name,
                            arguments=part.input,
                        ),
                    )
                )

        input_tokens = 0
        output_tokens = 0
        if resp.usage:
            input_tokens = resp.usage.input_tokens
            output_tokens = resp.usage.output_tokens

        return Message(
            role="assistant",
            name=self.model_name,
            content=message_segments,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def stream(
        self,
        system_prompt: str,
        messages: Messages,
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        thinking: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[MessageStreamEvent]:
        if not tools:
            tools = []

        segment_indexes: dict[tuple[str, int], int] = {}
        active_block_index: int | None = None
        active_segment_type: str | None = None
        active_tool: tuple[str, str] | None = None

        # 累积内容
        accumulated_content: dict[int, str] = {}
        accumulated_thinking: dict[int, str] = {}
        accumulated_signature: dict[int, str] = {}  # 累积 signature delta

        event_index = 0

        def _next_event_index() -> int:
            nonlocal event_index
            current = event_index
            event_index += 1
            return current

        async with self.client.messages.stream(
            **self._build_request_kwargs(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                thinking=thinking,
                **kwargs,
            )
        ) as stream:
            async for event in stream:
                if isinstance(event, RawMessageStartEvent):
                    continue

                elif isinstance(event, RawContentBlockStartEvent):
                    active_block_index = event.index
                    accumulated_content[event.index] = ""
                    accumulated_thinking[event.index] = ""
                    accumulated_signature[event.index] = ""

                    if isinstance(event.content_block, TextBlock):
                        active_segment_type = "text"
                        self._get_segment_index(
                            segment_indexes,
                            segment_type="text",
                            block_index=event.index,
                        )
                    elif isinstance(event.content_block, ThinkingBlock):
                        active_segment_type = "think"
                        self._get_segment_index(
                            segment_indexes,
                            segment_type="think",
                            block_index=event.index,
                        )
                    elif isinstance(event.content_block, ToolUseBlock):
                        active_segment_type = "tool"
                        active_tool = (
                            event.content_block.id,
                            event.content_block.name,
                        )
                        self._get_segment_index(
                            segment_indexes,
                            segment_type="tool",
                            block_index=event.index,
                        )
                    else:
                        active_segment_type = None
                        active_tool = None

                elif isinstance(event, RawContentBlockDeltaEvent):
                    if active_block_index is None:
                        continue

                    delta = event.delta

                    if isinstance(delta, TextDelta) and active_segment_type == "text":
                        text = delta.text
                        if not text:
                            continue
                        accumulated_content[active_block_index] += text
                        yield MessageStreamDeltaEvent(
                            segment=TextDetailSegment(
                                text=text,
                                index=self._get_segment_index(
                                    segment_indexes,
                                    segment_type="text",
                                    block_index=active_block_index,
                                ),
                            ),
                            index=_next_event_index(),
                        )

                    elif isinstance(delta, ThinkingDelta):
                        if not thinking:
                            continue
                        if active_segment_type != "think":
                            continue
                        thinking_text = delta.thinking
                        if not thinking_text:
                            continue
                        accumulated_thinking[active_block_index] += thinking_text
                        yield MessageStreamDeltaEvent(
                            segment=ThinkDetailSegment(
                                thought_process=thinking_text,
                                index=self._get_segment_index(
                                    segment_indexes,
                                    segment_type="think",
                                    block_index=active_block_index,
                                ),
                            ),
                            index=_next_event_index(),
                        )

                    # 3.3 Signature delta
                    elif isinstance(delta, SignatureDelta):
                        if not thinking:
                            continue
                        if active_segment_type != "think":
                            continue
                        sig = delta.signature
                        if sig:
                            accumulated_signature[active_block_index] += sig

                    elif isinstance(delta, InputJSONDelta):
                        if active_segment_type != "tool" or active_tool is None:
                            continue
                        partial_json = delta.partial_json
                        if not partial_json:
                            continue
                        tool_call_id, tool_name = active_tool
                        yield MessageStreamDeltaEvent(
                            segment=ToolCallDetailSegment(
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                partial_arguments=partial_json,
                                # 注意：snapshot 可能不存在于 RawContentBlockDeltaEvent
                                # 需要从外部累积或解析 partial_json
                                arguments=None,  # 在 stop 事件时填充完整 JSON
                                index=self._get_segment_index(
                                    segment_indexes,
                                    segment_type="tool",
                                    block_index=active_block_index,
                                ),
                            ),
                            index=_next_event_index(),
                        )

                elif isinstance(event, RawContentBlockStopEvent):
                    if isinstance(event.content_block, TextBlock):
                        yield MessageStreamCompleteEvent(
                            segment=TextSegment(
                                text=event.content_block.text,
                            ),
                            index=_next_event_index(),
                        )

                    elif isinstance(event.content_block, ThinkingBlock):
                        if thinking:
                            final_signature = accumulated_signature.get(event.index) or event.content_block.signature
                            yield MessageStreamCompleteEvent(
                                segment=ThinkSegment(
                                    thought_process=event.content_block.thinking,
                                    signature=final_signature,
                                ),
                                index=_next_event_index(),
                            )
                        accumulated_thinking.pop(event.index, None)
                        accumulated_signature.pop(event.index, None)

                    elif isinstance(event.content_block, ToolUseBlock):
                        tool_block = event.content_block
                        yield MessageStreamCompleteEvent(
                            segment=ToolSegment(
                                tool_call_id=tool_block.id,
                                tool_name=tool_block.name,
                                arguments=tool_block.input,
                            ),
                            index=_next_event_index(),
                        )

                    # 重置状态
                    if active_block_index == event.index:
                        active_block_index = None
                        active_segment_type = None
                        active_tool = None

                # 5. Message Delta
                elif isinstance(event, RawMessageDeltaEvent):
                    if event.usage:
                        yield MessageStreamCompleteEvent(
                            segment=to_usage_segment(usage=event.usage),
                            index=_next_event_index(),
                        )
                    if event.delta.stop_reason is not None:
                        yield MessageStreamCompleteEvent(
                            segment=StopSegment.from_raw_reason(event.delta.stop_reason),
                            index=_next_event_index(),
                        )

                # 6. Message Stop
                elif isinstance(event, RawMessageStopEvent):
                    continue


def message_to_anthropic(message: Message) -> list[MessageParam]:
    # In Anthropic API tool call result is user message.
    # {
    #   "role": "user",
    #   "content": [
    #     {
    #       "type": "tool_result",
    #       "tool_use_id": "toolu_01A09q90qw90lq917835lq9",
    #       "content": "15 degrees"
    #     }
    #   ]
    # }
    role = "assistant" if message.role == "assistant" else "user"
    content: list[TextBlockParam | ThinkingBlockParam | ToolUseBlockParam | ToolResultBlockParam] = []
    tool_calls_by_id = {tool_call.id: tool_call for tool_call in message.tool_calls}
    consumed_tool_call_ids: set[str] = set()

    for segment in message.content:
        match segment:
            case ToolResultSegment(tool_call_id=tool_call_id, content=result, is_error=is_error):
                # https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls
                # Tool result blocks must immediately
                # follow their corresponding tool use blocks in the message history.
                # You cannot include any messages
                # between the assistant's tool use message and the user's tool result message.
                # In the user message containing tool results,
                # the tool_result blocks must come FIRST in the content array.
                # Any text must come AFTER all tool results.
                content.insert(
                    0,
                    ToolResultBlockParam(
                        type="tool_result",
                        tool_use_id=tool_call_id,
                        content=result,
                        is_error=is_error,
                    ),
                )
            case TextSegment(text=text):
                content.append(
                    TextBlockParam(
                        type="text",
                        text=text,
                    )
                )
            case ThinkSegment(thought_process=thinking_text, signature=sig):
                # Convert ThinkSegment back to ThinkingBlockParam for API
                # Signature is required by Anthropic for thinking blocks in input
                if sig:
                    content.append(
                        ThinkingBlockParam(
                            type="thinking",
                            thinking=thinking_text,
                            signature=sig,
                        )
                    )
            case ToolSegment(tool_call_id=tool_call_id):
                tool_call = tool_calls_by_id.get(tool_call_id)
                if tool_call is None:
                    continue
                consumed_tool_call_ids.add(tool_call_id)
                content.append(
                    ToolUseBlockParam(
                        type="tool_use",
                        id=tool_call.id,
                        name=tool_call.function.name,
                        input=tool_call.function.arguments,  # type: ignore
                    )
                )
            case _:
                continue

    for tool_call in message.tool_calls:
        if tool_call.id in consumed_tool_call_ids:
            continue
        content.append(
            ToolUseBlockParam(
                type="tool_use",
                id=tool_call.id,
                name=tool_call.function.name,
                input=tool_call.function.arguments,  # type: ignore
            )
        )

    if not content:
        return []
    return [MessageParam(role=role, content=content)]


def tool_call_to_anthropic_tool_use(
    tool_call: Tool,
) -> ToolParam:
    return {
        "name": tool_call.name,
        "input_schema": tool_call.parameters,  # type: ignore
        "description": tool_call.description,
    }


def to_usage_segment(
    *,
    usage: MessageDeltaUsage,
) -> UsageSegment:
    return UsageSegment(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cached_tokens=usage.cache_read_input_tokens,
    )


if __name__ == "__main__":
    import asyncio
    import os

    from dotenv import load_dotenv

    os.environ["LOG_LEVEL"] = "TRACE"
    load_dotenv()

    from omg_cli.log import logger
    from omg_cli.tool import register_tool

    async def _test_stream() -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                """Set ANTHROPIC_API_KEY before running _test_stream().
                This helper exercises the messages.stream endpoint used by AnthropicAPI.stream()."""
            )

        base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

        anthropic_api = AnthropicAPI(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

        @register_tool
        async def get_weather(city: str) -> dict[str, str]:
            """获取指定城市的天气信息。"""
            return {"city": city, "forecast": "多云，25°C"}

        print("Streaming response:\n", end="", flush=True)
        messages: list[Message] = [
            Message(
                role="user",
                name="user1",
                content=[TextSegment(text="巴黎和上海的天气怎么样？请连续调用 tool call 获取两个城市的天气信息。")],
            )
        ]

        # 第一轮：获取 tool calls
        assistant_segments: list[Any] = []
        tool_calls: list[ToolCall] = []

        async for event in anthropic_api.stream(
            system_prompt="You are a helpful assistant.",
            messages=messages,
            tools=[get_weather],
        ):
            logger.debug(f"event: {event}")

            if isinstance(event, MessageStreamDeltaEvent):
                match event.segment:
                    case TextDetailSegment(text=text):
                        print(text, end="", flush=True)
                    case ThinkDetailSegment(thought_process=thought_process):
                        print(f"[思考: {thought_process}]", end="", flush=True)
                    case ToolCallDetailSegment(partial_arguments=partial_arguments):
                        print(partial_arguments, end="", flush=True)

            elif isinstance(event, MessageStreamCompleteEvent):
                match event.segment:
                    case TextSegment() as segment:
                        assistant_segments.append(segment)
                    case ThinkSegment() as segment:
                        assistant_segments.append(segment)
                    case ToolSegment() as segment:
                        assistant_segments.append(segment)
                        tool_calls.append(segment.to_tool_call())
                    case UsageSegment() as segment:
                        print(
                            f"\n[Usage] input_tokens={segment.input_tokens}, \
                            output_tokens={segment.output_tokens}, cached_tokens={segment.cached_tokens}"
                        )

        # 如果有 tool calls，构建 assistant message 并追加到对话
        if tool_calls:
            assistant_msg = Message(
                role="assistant",
                name=model,
                content=assistant_segments,
                tool_calls=tool_calls,
            )
            messages.append(assistant_msg)

            # 执行 tools 并构建 tool result messages
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.arguments
                print(f"\n\n[Tool Call] {tool_name}({tool_args})")

                # 执行工具
                if tool_name == "get_weather":
                    result = await get_weather(**tool_args)
                    result_str = str(result)
                else:
                    result_str = f"Unknown tool: {tool_name}"

                print(f"[Tool Result] {result_str}")

                # Anthropic: tool result 是 user message
                tool_result_msg = Message(
                    role="user",
                    content=[
                        ToolResultSegment(
                            tool_call_id=tool_call.id,
                            tool_name=tool_name,
                            content=result_str,
                        )
                    ],
                )
                messages.append(tool_result_msg)

            # 第二轮：发送 tool results 获取最终回复
            print("\n\n--- Final Response ---\n", end="", flush=True)
            final_segments: list[Any] = []

            async for event in anthropic_api.stream(
                system_prompt="You are a helpful assistant.",
                messages=messages,
                tools=[get_weather],
            ):
                logger.debug(f"final event: {event}")

                if isinstance(event, MessageStreamDeltaEvent):
                    match event.segment:
                        case TextDetailSegment(text=text):
                            print(text, end="", flush=True)
                        case ThinkDetailSegment(thought_process=thought_process):
                            print(f"[思考: {thought_process}]", end="", flush=True)

                elif isinstance(event, MessageStreamCompleteEvent):
                    match event.segment:
                        case TextSegment() as segment:
                            final_segments.append(segment)
                        case ThinkSegment() as segment:
                            final_segments.append(segment)

            # 构建最终 assistant message
            if final_segments:
                final_msg = Message(
                    role="assistant",
                    name=model,
                    content=final_segments,
                )
                messages.append(final_msg)

        print("\n\n--- Conversation History ---")
        for msg in messages:
            print(f"[{msg.role}] {msg.content}")

    asyncio.run(_test_stream())
