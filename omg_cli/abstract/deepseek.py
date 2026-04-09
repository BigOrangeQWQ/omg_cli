from collections.abc import AsyncIterator
import json
from typing import Any

from loguru import logger
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnionParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from openai.types.shared_params.function_definition import FunctionDefinition

from omg_cli.abstract.utils import Messages, to_messages
from omg_cli.types.message import (
    ImageSegment,
    MessageSegment,
    MessageStreamCompleteEvent,
    MessageStreamDeltaEvent,
    MessageStreamEvent,
    SegmentType,
    StopSegment,
    TextDetailSegment,
    TextSegment,
    ThinkDetailSegment,
    ThinkSegment,
    ToolCall,
    ToolCallDetailSegment,
    ToolCallFunctionBody,
    ToolSegment,
    UsageSegment,
)
from omg_cli.types.message import (
    Message as ChatMessage,
)
from omg_cli.types.tool import Tool

from .openai_legacy import OpenAILegacy


class DeepSeekAPI(OpenAILegacy):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        stream: bool = False,
    ) -> None:
        super().__init__(api_key, model, base_url, stream)
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        # 这个变量用于储存正在生成的思考内容
        # 若 thinking_content 不为空，则表示相同前缀的 reasoning content应该被包含在 message 中，而非排除在外
        # 每次完整的思考结束后，thinking_content 会被清空
        self._thinking_content = ""

    @property
    def type(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def thinking_supported(self) -> bool:
        return True

    def _get_segment_index(
        self,
        segment_indexes: dict[tuple[SegmentType, str], int],
        *,
        segment_type: SegmentType,
        item_key: str | int,
    ) -> int:
        key = (segment_type, str(item_key))
        if key not in segment_indexes:
            segment_indexes[key] = len(segment_indexes)
        return segment_indexes[key]

    @staticmethod
    def _get_extra_field(source: Any, field_name: str) -> Any:
        value = getattr(source, field_name, None)
        if value is not None:
            return value

        model_extra = getattr(source, "model_extra", None)
        if isinstance(model_extra, dict):
            return model_extra.get(field_name)

        return None

    def _build_openai_messages(
        self,
        *,
        system_prompt: str,
        messages: "Messages",
    ) -> list[ChatCompletionMessageParam]:
        openai_messages: list[ChatCompletionMessageParam] = []
        if system_prompt:
            openai_messages.append(
                ChatCompletionSystemMessageParam(
                    role="system",
                    content=system_prompt,
                )
            )

        conversation = list(to_messages(messages))
        last_assistant_index = None
        for index, message in enumerate(conversation):
            if message.role == "assistant":
                last_assistant_index = index

        for index, message in enumerate(conversation):
            include_reasoning = index == last_assistant_index and message.in_thinking
            openai_messages.extend(
                to_openai_messages(
                    message,
                    include_reasoning=include_reasoning,
                )
            )

        return openai_messages

    async def chat(
        self,
        system_prompt: str,
        messages: "Messages",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        thinking: bool = False,
        **kwargs,
    ) -> ChatMessage:
        """
        Chat with the model and return the complete response as a single message.
        This is a non-streaming call and will wait for the full response before returning.
        """
        if thinking:
            raise NotImplementedError("Thinking mode not implemented in non-streaming chat")

        _messages = self._build_openai_messages(
            system_prompt=system_prompt,
            messages=messages,
        )
        if tools is None:
            tools = []
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        _tools: list[ChatCompletionFunctionToolParam] = [tool_to_openai_function(tool) for tool in tools]

        response: ChatCompletion = await self.client.chat.completions.create(
            model=self.model,
            messages=_messages,
            stream=False,
            tools=_tools,
            **kwargs,
        )

        input_tokens = 0
        output_tokens = 0
        if response.usage:
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

        tool_calls: list[ToolCall] = []
        message_segments: list[MessageSegment] = []
        for message in response.choices:
            tc = message.message.tool_calls or []
            reasoning_content = self._get_extra_field(message.message, "reasoning_content")
            if reasoning_content:
                message_segments.append(ThinkSegment(thought_process=str(reasoning_content)))
            if message.message.content:
                message_segments.append(TextSegment(text=message.message.content))
            for tc in tc:
                if tc.type == "function":
                    tool_calls.append(
                        ToolCall(
                            type="function",
                            id=tc.id,
                            function=ToolCallFunctionBody(
                                name=tc.function.name,
                                arguments=parse_tool_arguments(tc.function.arguments),
                            ),
                        )
                    )
                    message_segments.append(ToolSegment(tool_call_id=tc.id, tool_name=tc.function.name))
        return ChatMessage(
            role="assistant",
            name=self.model,
            content=message_segments,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def stream(
        self,
        system_prompt: str,
        messages: "Messages",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        thinking: bool = False,
        **kwargs,
    ) -> AsyncIterator[MessageStreamEvent]:
        if thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        _messages = self._build_openai_messages(
            system_prompt=system_prompt,
            messages=messages,
        )

        if tools is None:
            tools = []
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        _tools: list[ChatCompletionFunctionToolParam] = [tool_to_openai_function(tool) for tool in tools]

        stream: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
            model=self.model,
            messages=_messages,
            stream=True,
            tools=_tools,
            stream_options={"include_usage": True},
            **kwargs,
        )

        segment_indexes: dict[tuple[SegmentType, str], int] = {}
        event_index = 0

        def _next_event_index() -> int:
            nonlocal event_index
            current = event_index
            event_index += 1
            return current

        text_buffers: dict[int, list[str]] = {}
        think_buffers: dict[int, list[str]] = {}
        tool_states: dict[tuple[int, int], dict[str, str]] = {}
        completed_tools: set[tuple[int, int]] = set()
        completed_text_choices: set[int] = set()
        completed_think_choices: set[int] = set()

        async for chunk in stream:
            if not isinstance(chunk, ChatCompletionChunk):
                continue

            reasoning_tokens = None
            cached_tokens = None
            if chunk.usage is not None and chunk.usage.completion_tokens_details is not None:
                reasoning_tokens = chunk.usage.completion_tokens_details.reasoning_tokens

            if chunk.usage is not None and chunk.usage.prompt_tokens_details is not None:
                cached_tokens = chunk.usage.prompt_tokens_details.cached_tokens

                yield MessageStreamCompleteEvent(
                    segment=UsageSegment(
                        input_tokens=chunk.usage.prompt_tokens,
                        output_tokens=chunk.usage.completion_tokens,
                        total_tokens=chunk.usage.total_tokens,
                        cached_tokens=cached_tokens,
                        reasoning_tokens=reasoning_tokens,
                    ),
                    index=_next_event_index(),
                )

            for choice in chunk.choices:
                choice_index = choice.index
                delta = choice.delta

                reasoning_delta = self._get_extra_field(delta, "reasoning_content")
                if reasoning_delta:
                    think_buffers.setdefault(choice_index, []).append(str(reasoning_delta))
                    think_segment_index = self._get_segment_index(
                        segment_indexes,
                        segment_type="think",
                        item_key=choice_index,
                    )
                    yield MessageStreamDeltaEvent(
                        segment=ThinkDetailSegment(
                            thought_process=str(reasoning_delta),
                            index=think_segment_index,
                        ),
                        index=_next_event_index(),
                    )

                text_delta = delta.content
                if text_delta:
                    text_buffers.setdefault(choice_index, []).append(text_delta)
                    text_segment_index = self._get_segment_index(
                        segment_indexes,
                        segment_type="text",
                        item_key=choice_index,
                    )
                    yield MessageStreamDeltaEvent(
                        segment=TextDetailSegment(text=text_delta, index=text_segment_index),
                        index=_next_event_index(),
                    )

                tool_deltas = delta.tool_calls or []
                for tool_delta in tool_deltas:
                    if not isinstance(tool_delta, ChoiceDeltaToolCall):
                        continue

                    tool_index = tool_delta.index
                    key = (choice_index, tool_index)
                    state = tool_states.setdefault(key, {})

                    function_delta = tool_delta.function
                    if function_delta is None:
                        continue

                    tool_name_delta = function_delta.name
                    arguments_delta = function_delta.arguments

                    if tool_delta.id:
                        state["id"] = tool_delta.id

                    if isinstance(function_delta, ChoiceDeltaToolCallFunction):
                        if tool_name_delta:
                            state["name"] = tool_name_delta

                        if arguments_delta:
                            state.setdefault("arguments", "")
                            state["arguments"] += arguments_delta
                            if state["id"] and state["name"]:
                                tool_segment_index = self._get_segment_index(
                                    segment_indexes,
                                    segment_type="tool",
                                    item_key=f"{state['id']}:{tool_index}",
                                )
                                yield MessageStreamDeltaEvent(
                                    segment=ToolCallDetailSegment(
                                        tool_call_id=state["id"],
                                        tool_name=state["name"],
                                        partial_arguments=arguments_delta,
                                        index=tool_segment_index,
                                    ),
                                    index=_next_event_index(),
                                )

                if choice.finish_reason is not None:
                    stop_segment_index = self._get_segment_index(
                        segment_indexes,
                        segment_type="stop",
                        item_key=choice_index,
                    )
                    yield MessageStreamCompleteEvent(
                        segment=StopSegment.from_raw_reason(choice.finish_reason).model_copy(
                            update={"index": stop_segment_index}
                        ),
                        index=_next_event_index(),
                    )

                    if choice_index not in completed_think_choices and choice_index in think_buffers:
                        thought_process = "".join(think_buffers[choice_index])
                        if thought_process:
                            think_segment_index = self._get_segment_index(
                                segment_indexes,
                                segment_type="think",
                                item_key=choice_index,
                            )
                            yield MessageStreamCompleteEvent(
                                segment=ThinkSegment(
                                    thought_process=thought_process,
                                ),
                                index=_next_event_index(),
                            )
                        completed_think_choices.add(choice_index)

                    if choice_index not in completed_text_choices and choice_index in text_buffers:
                        text = "".join(text_buffers[choice_index])
                        if text:
                            text_segment_index = self._get_segment_index(
                                segment_indexes,
                                segment_type="text",
                                item_key=choice_index,
                            )
                            yield MessageStreamCompleteEvent(
                                segment=TextSegment(text=text),
                                index=_next_event_index(),
                            )
                        completed_text_choices.add(choice_index)

                    if choice.finish_reason in {"tool_calls", "function_call"}:
                        for (
                            tool_choice_index,
                            tool_index,
                        ), state in tool_states.items():
                            if tool_choice_index != choice_index:
                                continue
                            tool_key = (tool_choice_index, tool_index)
                            if tool_key in completed_tools:
                                continue
                            if not state["name"]:
                                continue
                            tool_call_id = state["id"] or f"tool_call_{choice_index}_{tool_index}"
                            tool_segment_index = self._get_segment_index(
                                segment_indexes,
                                segment_type="tool",
                                item_key=f"{tool_call_id}:{tool_index}",
                            )
                            yield MessageStreamCompleteEvent(
                                segment=ToolSegment(
                                    tool_call_id=tool_call_id,
                                    tool_name=state["name"],
                                    arguments=parse_tool_arguments(state["arguments"]),
                                ),
                                index=_next_event_index(),
                            )
                            completed_tools.add(tool_key)

        for choice_index, thinking_parts in think_buffers.items():
            if choice_index in completed_think_choices:
                continue
            thought_process = "".join(thinking_parts)
            if not thought_process:
                continue
            think_segment_index = self._get_segment_index(
                segment_indexes,
                segment_type="think",
                item_key=choice_index,
            )
            yield MessageStreamCompleteEvent(
                segment=ThinkSegment(thought_process=thought_process),
                index=_next_event_index(),
            )

        for choice_index, text_parts in text_buffers.items():
            if choice_index in completed_text_choices:
                continue
            text = "".join(text_parts)
            if not text:
                continue
            text_segment_index = self._get_segment_index(
                segment_indexes,
                segment_type="text",
                item_key=choice_index,
            )
            yield MessageStreamCompleteEvent(
                segment=TextSegment(text=text),
                index=_next_event_index(),
            )

        for (choice_index, tool_index), state in tool_states.items():
            tool_key = (choice_index, tool_index)
            if tool_key in completed_tools:
                continue
            if not state["name"]:
                continue
            tool_call_id = state["id"] or f"tool_call_{choice_index}_{tool_index}"
            tool_segment_index = self._get_segment_index(
                segment_indexes,
                segment_type="tool",
                item_key=f"{tool_call_id}:{tool_index}",
            )
            yield MessageStreamCompleteEvent(
                segment=ToolSegment(
                    tool_call_id=tool_call_id,
                    tool_name=state["name"],
                    arguments=parse_tool_arguments(state["arguments"]),
                ),
                index=_next_event_index(),
            )


def to_openai_messages(messages: ChatMessage, include_reasoning: bool = False) -> list[ChatCompletionMessageParam]:
    completion_messsages: list[ChatCompletionMessageParam] = []
    match messages.role:
        case "user":
            user_segments: list[ChatCompletionContentPartParam] = []
            for segment in messages.content:
                match segment:
                    case TextSegment(text=text):
                        user_segments.append(
                            ChatCompletionContentPartTextParam(
                                type="text",
                                text=text,
                            )
                        )
                    case ImageSegment(url=url):
                        user_segments.append(
                            ChatCompletionContentPartImageParam(
                                type="image_url",
                                image_url={"detail": "auto", "url": url},
                            )
                        )
                    case _:
                        raise NotImplementedError(f"Segment type {type(segment)} not supported in user message")
            completion_messsages.append(
                ChatCompletionUserMessageParam(
                    role="user",
                    content=user_segments,
                )
            )
        case "assistant":
            assistant_text_parts: list[str] = []
            reasoning_parts: list[str] = []
            for segment in messages.content:
                match segment:
                    case TextSegment(text=text):
                        assistant_text_parts.append(text)
                    case ThinkSegment(thought_process=thought_process):
                        reasoning_parts.append(thought_process)
                    case ImageSegment():
                        raise NotImplementedError("Image segments not supported in assistant message")
            tools_calls: list[ChatCompletionMessageToolCallUnionParam] = []
            for tool_call in messages.tool_calls:
                tools_calls.append(
                    ChatCompletionMessageFunctionToolCallParam(
                        id=tool_call.id,
                        function={
                            "name": tool_call.function.name,
                            "arguments": json.dumps(tool_call.function.arguments),
                        },
                        type="function",
                    )
                )
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(assistant_text_parts),
            }

            if tools_calls:
                assistant_message["tool_calls"] = tools_calls

            # This argument is DeepSeek-specific and allows sending reasoning content that is
            # separate from the main text content.
            if reasoning_parts and include_reasoning:
                assistant_message["reasoning_content"] = "".join(reasoning_parts)
            completion_messsages.append(assistant_message)  # type: ignore[arg-type]
        case "tool":
            tool_segment = next(
                (segment for segment in messages.content if isinstance(segment, ToolSegment)),
                None,
            )
            if tool_segment is None:
                raise ValueError("Tool messages must include a ToolSegment with tool_call_id")
            completion_messsages.append(  # type: ignore[arg-type]
                {
                    "role": "tool",
                    "tool_call_id": tool_segment.tool_call_id,
                    "content": messages.text,
                }
            )
        case "system":
            completion_messsages.append(ChatCompletionSystemMessageParam(role="system", content=messages.text))

    return completion_messsages


def to_openai_response_input(messages: ChatMessage) -> list[dict[str, Any]]:
    response_items: list[dict[str, Any]] = []
    match messages.role:
        case "user" | "system" | "developer":
            response_items.append(
                {
                    "type": "message",
                    "role": messages.role,
                    "content": to_openai_response_content(messages.content),
                }
            )
        case "assistant":
            assistant_content = to_openai_response_content(messages.content)
            if assistant_content:
                response_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
            for tool_call in messages.tool_calls:
                response_items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "arguments": json.dumps(tool_call.function.arguments),
                        "status": "completed",
                    }
                )
        case "tool":
            tool_segment = next(
                (segment for segment in messages.content if isinstance(segment, ToolSegment)),
                None,
            )
            if tool_segment is None:
                raise ValueError("Tool messages must include a ToolSegment with the originating tool_call_id")
            response_items.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_segment.tool_call_id,
                    "output": messages.text,
                }
            )
    return response_items


def to_openai_response_content(segments: Any) -> list[dict[str, Any]]:
    response_content: list[dict[str, Any]] = []
    for segment in segments:
        match segment:
            case TextSegment(text=text):
                response_content.append(
                    {
                        "type": "input_text",
                        "text": text,
                    }
                )
            case ImageSegment(url=url):
                response_content.append(
                    {
                        "type": "input_image",
                        "image_url": url,
                        "detail": "auto",
                    }
                )
            case ThinkSegment() | ToolSegment():
                continue
            case _:
                raise NotImplementedError(f"Unsupported message segment type: {type(segment)}")
    return response_content


def tool_to_openai_response_function(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
        "strict": False,
    }


def parse_tool_arguments(arguments: str) -> dict[str, Any]:
    if not arguments:
        return {}
    parsed_arguments = json.loads(arguments)
    if not isinstance(parsed_arguments, dict):
        raise TypeError("Tool call arguments must decode to a JSON object")
    return parsed_arguments


def tool_to_openai_function(tool: Tool) -> ChatCompletionFunctionToolParam:
    return ChatCompletionFunctionToolParam(
        type="function",
        function=FunctionDefinition(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,  # type: ignore
        ),
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
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                """Set OPENAI_API_KEY before running _test_stream().
                This helper exercises the chat.completions stream endpoint used by OpenAILegacy.stream()."""
            )

        base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
        model = os.getenv("OPENAI_MODEL", "deepseek-chat")

        openai_api = DeepSeekAPI(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

        @register_tool
        async def get_weather(city: str) -> dict[str, str]:
            """获取天气信息。"""
            return {"city": city, "forecast": "多云"}

        print("Streaming response:\n", end="", flush=True)
        messages = [
            ChatMessage(
                role="user",
                name="user1",
                content=[
                    TextSegment(
                        text="巴黎和上海的天气怎么样？请连续调用toolcall获取两个城市的天气信息，并在思考过程中解释你是如何调用toolcall的。"
                    )
                ],
            )
        ]
        async for event in openai_api.stream(
            system_prompt="You are a helpful assistant.",
            messages=messages,
            tools=[get_weather],
        ):
            if not isinstance(event, MessageStreamDeltaEvent):
                logger.debug(f"non-delta: {event}")

                if isinstance(event, MessageStreamCompleteEvent):
                    if isinstance(event.segment, TextSegment):
                        messages.append(event.to_message())

            logger.debug(f"delta: {event}")

            match event.segment:
                case TextDetailSegment(text=text):
                    print(text, end="", flush=True)
                case ThinkDetailSegment(thought_process=thought_process):
                    print(thought_process, end="", flush=True)
                case ToolCallDetailSegment(partial_arguments=partial_arguments):
                    print(partial_arguments, end="", flush=True)
                case _:
                    continue

    asyncio.run(_test_stream())
