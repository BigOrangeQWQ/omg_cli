from collections.abc import AsyncIterator
from functools import cache
import json
from typing import TYPE_CHECKING, Any, override

from loguru import logger
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
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

from src.omg_cli.abstract import ChatAdapter
from src.omg_cli.abstract.utils import Messages, to_messages
from src.omg_cli.types.message import (
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
from src.omg_cli.types.message import (
    Message as ChatMessage,
)
from src.omg_cli.types.tool import Tool

if TYPE_CHECKING:
    from openai.types.chat.chat_completion_assistant_message_param import (
        ContentArrayOfContentPart,
    )


class OpenAILegacy(ChatAdapter):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        stream: bool = False,
        thinking_supported: bool = False,
    ) -> None:
        super().__init__(api_key, model, base_url, stream)
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self._thinking_supported = thinking_supported

    @property
    def type(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def thinking_supported(self) -> bool:
        return self._thinking_supported

    @override
    @cache
    async def list_models(self) -> list[str]:
        models = await self.client.models.list()
        return [model.id for model in models.data if model.id]

    @override
    async def context_length(self) -> int:
        """Get the model's context window length in tokens.

        Uses a mapping table since OpenAI's API doesn't expose max_context_length.
        Returns 100000 (100K) for unknown models.
        """
        return 100000

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

    async def chat(
        self,
        system_prompt: str,
        messages: "Messages",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> ChatMessage:
        if tools is None:
            tools = []
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        _messages: list[ChatCompletionMessageParam] = []
        if system_prompt:
            _messages.append(
                ChatCompletionSystemMessageParam(
                    role="system",
                    content=system_prompt,
                )
            )
        messages = to_messages(messages)
        for msg in messages:
            _messages.extend(to_openai_messages(msg))

        _tools: list[ChatCompletionFunctionToolParam] = [tool_to_openai_function(tool) for tool in tools]

        response: ChatCompletion = await self.client.chat.completions.create(
            model=self.model,
            messages=_messages,
            stream=False,
            tools=_tools,
            **kwargs,
        )

        if self.stream_enabled or not isinstance(response, ChatCompletion):
            raise NotImplementedError("Streaming not implemented yet")

        input_tokens = 0
        output_tokens = 0
        if response.usage:
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

        tool_calls: list[ToolCall] = []
        message_segments: list[MessageSegment] = []
        for message in response.choices:
            tc = message.message.tool_calls or []
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
        if tools is None:
            tools = []
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if thinking:
            raise NotImplementedError("Thinking mode not implemented yet")

        _messages: list[ChatCompletionMessageParam] = []
        if system_prompt:
            _messages.append(
                ChatCompletionSystemMessageParam(
                    role="system",
                    content=system_prompt,
                )
            )
        messages = to_messages(messages)
        for msg in messages:
            _messages.extend(to_openai_messages(msg))

        logger.trace(f"Streaming chat with messages: {_messages[:5]} and tools: {[tool.name for tool in tools]}")
        _tools: list[ChatCompletionFunctionToolParam] = [tool_to_openai_function(tool) for tool in tools]

        stream: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
            model=self.model,
            messages=_messages,
            stream=True,
            tools=_tools,
            stream_options={"include_usage": True},
            **kwargs,
        )
        event_index = 0

        def _next_event_index() -> int:
            nonlocal event_index
            current = event_index
            event_index += 1
            return current

        segment_indexes: dict[tuple[SegmentType, str], int] = {}
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

                text_delta = delta.content
                if text_delta:
                    text_buffers.setdefault(choice_index, []).append(text_delta)
                    yield MessageStreamDeltaEvent(
                        segment=TextDetailSegment(
                            text=text_delta,
                            index=self._get_segment_index(
                                segment_indexes,
                                segment_type="text",
                                item_key=choice_index,
                            ),
                        ),
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
                                yield MessageStreamDeltaEvent(
                                    segment=ToolCallDetailSegment(
                                        tool_call_id=state["id"],
                                        tool_name=state["name"],
                                        partial_arguments=arguments_delta,
                                        index=self._get_segment_index(
                                            segment_indexes,
                                            segment_type="tool",
                                            item_key=f"{state['id']}:{tool_index}",
                                        ),
                                    ),
                                    index=_next_event_index(),
                                )

                if choice.finish_reason is not None:
                    yield MessageStreamCompleteEvent(
                        segment=StopSegment.from_raw_reason(choice.finish_reason),
                        index=self._get_segment_index(
                            segment_indexes,
                            segment_type="stop",
                            item_key=choice_index,
                        ),
                    )

                    if choice_index not in completed_think_choices and choice_index in think_buffers:
                        thought_process = "".join(think_buffers[choice_index])
                        if thought_process:
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
                            yield MessageStreamCompleteEvent(
                                segment=TextSegment(
                                    text=text,
                                ),
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
            yield MessageStreamCompleteEvent(
                segment=ThinkSegment(
                    thought_process=thought_process,
                ),
                index=_next_event_index(),
            )

        for choice_index, text_parts in text_buffers.items():
            if choice_index in completed_text_choices:
                continue
            text = "".join(text_parts)
            if not text:
                continue
            yield MessageStreamCompleteEvent(
                segment=TextSegment(
                    text=text,
                ),
                index=_next_event_index(),
            )

        for (choice_index, tool_index), state in tool_states.items():
            tool_key = (choice_index, tool_index)
            if tool_key in completed_tools:
                continue
            if not state["name"]:
                continue
            tool_call_id = state["id"] or f"tool_call_{choice_index}_{tool_index}"
            yield MessageStreamCompleteEvent(
                segment=ToolSegment(
                    tool_call_id=tool_call_id,
                    tool_name=state["name"],
                    arguments=parse_tool_arguments(state["arguments"]),
                ),
                index=_next_event_index(),
            )


def to_openai_messages(messages: ChatMessage) -> list[ChatCompletionMessageParam]:
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
            assistant_segments: list[ContentArrayOfContentPart] = []
            for segment in messages.content:
                match segment:
                    case TextSegment(text=text):
                        assistant_segments.append(
                            ChatCompletionContentPartTextParam(
                                type="text",
                                text=text,
                            )
                        )
                    case ImageSegment(url=url):
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
            assistant_message: ChatCompletionAssistantMessageParam = ChatCompletionAssistantMessageParam(
                role="assistant",
                content=assistant_segments,
            )
            if tools_calls:
                assistant_message["tool_calls"] = tools_calls
            completion_messsages.append(assistant_message)  # type: ignore[arg-type]
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

    load_dotenv()

    async def _test_stream() -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Set OPENAI_API_KEY before running _test_stream(). \
                This helper exercises the chat.completions stream endpoint used by OpenAILegacy.stream()."
            )

        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("OPENAI_MODEL", "gpt-5.4")

        openai_api = OpenAILegacy(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

        print("Streaming response:\n", end="", flush=True)
        async for event in openai_api.stream(
            system_prompt="You are a helpful assistant.",
            messages=[
                ChatMessage(
                    role="user",
                    name="user1",
                    content=[TextSegment(text="Hello, how are you?")],
                )
            ],
            tools=[],
        ):
            if not isinstance(event, MessageStreamDeltaEvent):
                continue

            match event.segment:
                case TextDetailSegment(text=text):
                    print(text, end="", flush=True)
                case ThinkDetailSegment(thought_process=thought_process):
                    print(thought_process, end="", flush=True)
                case ToolCallDetailSegment(partial_arguments=partial_arguments):
                    print(partial_arguments, end="", flush=True)
                case _:
                    continue

        print()

    asyncio.run(_test_stream())
