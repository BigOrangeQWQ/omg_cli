from collections.abc import AsyncIterator
from functools import cache
import json
from typing import TYPE_CHECKING, Any, override

from openai import AsyncOpenAI
from openai.types.chat import (
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
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningTextDoneEvent,
    ResponseRefusalDeltaEvent,
    ResponseRefusalDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
)
from openai.types.responses.response_output_refusal import ResponseOutputRefusal
from openai.types.shared_params.function_definition import FunctionDefinition

from omg_cli.abstract import ChatAdapter
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

if TYPE_CHECKING:
    from openai.types.chat.chat_completion_assistant_message_param import (
        ContentArrayOfContentPart,
    )


class OpenAIAPI(ChatAdapter):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        stream: bool = False,
        max_input_tokens: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key, model, base_url, stream, max_input_tokens=max_input_tokens, **kwargs)
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    @property
    def type(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self.model

    @override
    @cache
    async def list_models(self) -> list[str]:
        models = await self.client.models.list()
        return [model.id for model in models.data if model.id]

    @override
    async def context_length(self) -> int:
        """Get the model's context window length in tokens.

        Uses a mapping table since OpenAI's API doesn't expose max_context_length.
        Returns 150000 (150K) for unknown models (Response API has higher limits).
        """
        if self.max_input_tokens:
            return self.max_input_tokens
        return 150000

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
            kwargs["max_output_tokens"] = max_tokens

        response_input: list[dict[str, Any]] = []
        for message in to_messages(messages):
            response_input.extend(to_openai_response_input(message))

        _tools = [tool_to_openai_response_function(tool) for tool in tools]

        response: Response = await self.client.responses.create(
            model=self.model,
            input=response_input,  # type: ignore
            tools=_tools,  # type: ignore
            instructions=system_prompt,
            **kwargs,
        )

        input_tokens = 0
        output_tokens = 0
        if response.usage:
            if response.usage.input_tokens is not None:
                input_tokens = response.usage.input_tokens
            if response.usage.output_tokens is not None:
                output_tokens = response.usage.output_tokens

        tool_calls: list[ToolCall] = []
        message_segments: list[MessageSegment] = []

        for output_item in response.output:
            if isinstance(output_item, ResponseOutputMessage):
                for content_item in output_item.content:
                    if isinstance(content_item, ResponseOutputText) and content_item.text:
                        message_segments.append(TextSegment(text=content_item.text))
                    elif isinstance(content_item, ResponseOutputRefusal) and content_item.refusal:
                        message_segments.append(TextSegment(text=content_item.refusal))
            elif isinstance(output_item, ResponseReasoningItem):
                reasoning_parts: list[str] = []
                for summary_item in output_item.summary:
                    if summary_item.text:
                        reasoning_parts.append(summary_item.text)
                if reasoning_parts:
                    message_segments.append(ThinkSegment(thought_process="".join(reasoning_parts)))
            elif isinstance(output_item, ResponseFunctionToolCall):
                call_id = output_item.call_id
                tool_name = output_item.name
                if not call_id or not tool_name:
                    continue

                tool_calls.append(
                    ToolCall(
                        type="function",
                        id=call_id,
                        function=ToolCallFunctionBody(
                            name=tool_name,
                            arguments=parse_tool_arguments(output_item.arguments),
                        ),
                    )
                )
                message_segments.append(ToolSegment(tool_call_id=call_id, tool_name=tool_name))

        if not message_segments and response.output_text:
            message_segments.append(TextSegment(text=response.output_text))

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
            kwargs["max_output_tokens"] = max_tokens
        if thinking:
            raise NotImplementedError("Thinking mode not implemented yet")

        response_input: list[dict[str, Any]] = []
        for message in to_messages(messages):
            response_input.extend(to_openai_response_input(message))

        response_tools = [tool_to_openai_response_function(tool) for tool in tools]

        segment_indexes: dict[tuple[SegmentType, str], int] = {}
        function_calls: dict[str, tuple[str, str]] = {}
        completed_function_calls: set[str] = set()

        stream_context = self.client.responses.stream(
            model=self.model,
            input=response_input,  # type: ignore
            tools=response_tools,  # type: ignore
            instructions=system_prompt,
            **kwargs,
        )

        event_index = 0

        def _next_event_index() -> int:
            nonlocal event_index
            current = event_index
            event_index += 1
            return current

        async with stream_context as stream:
            async for event in stream:
                if isinstance(event, ResponseTextDeltaEvent):
                    if not event.delta:
                        continue
                    yield MessageStreamDeltaEvent(
                        segment=TextDetailSegment(
                            text=event.delta,
                            index=self._get_segment_index(
                                segment_indexes,
                                segment_type="text",
                                item_key=f"{event.item_id}:{event.content_index}",
                            ),
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseTextDoneEvent):
                    yield MessageStreamCompleteEvent(
                        segment=TextSegment(
                            text=event.text,
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseReasoningTextDeltaEvent):
                    if not event.delta:
                        continue
                    yield MessageStreamDeltaEvent(
                        segment=ThinkDetailSegment(
                            thought_process=event.delta,
                            index=self._get_segment_index(
                                segment_indexes,
                                segment_type="think",
                                item_key=f"{event.item_id}:{event.content_index}",
                            ),
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseReasoningTextDoneEvent):
                    yield MessageStreamCompleteEvent(
                        segment=ThinkSegment(thought_process=event.text),
                        index=self._get_segment_index(
                            segment_indexes,
                            segment_type="think",
                            item_key=f"{event.item_id}:{event.content_index}",
                        ),
                    )
                elif isinstance(event, ResponseReasoningSummaryTextDeltaEvent):
                    if not event.delta:
                        continue
                    yield MessageStreamDeltaEvent(
                        segment=ThinkDetailSegment(
                            thought_process=event.delta,
                            index=self._get_segment_index(
                                segment_indexes,
                                segment_type="think",
                                item_key=f"{event.item_id}:{event.summary_index}",
                            ),
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseReasoningSummaryTextDoneEvent):
                    yield MessageStreamCompleteEvent(
                        segment=ThinkSegment(
                            thought_process=event.text,
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseRefusalDeltaEvent):
                    if not event.delta:
                        continue
                    yield MessageStreamDeltaEvent(
                        segment=TextDetailSegment(
                            text=event.delta,
                            index=self._get_segment_index(
                                segment_indexes,
                                segment_type="refusal",
                                item_key=f"{event.item_id}:{event.content_index}",
                            ),
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseRefusalDoneEvent):
                    yield MessageStreamCompleteEvent(
                        segment=TextSegment(
                            text=event.refusal,
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseOutputItemAddedEvent) and isinstance(
                    event.item, ResponseFunctionToolCall
                ):
                    if not event.item.id:
                        continue
                    function_calls[event.item.id] = (
                        event.item.call_id,
                        event.item.name,
                    )
                elif isinstance(event, ResponseFunctionCallArgumentsDeltaEvent):
                    if not event.delta:
                        continue
                    function_call = function_calls.get(event.item_id)
                    if function_call is None:
                        continue
                    call_id, tool_name = function_call
                    yield MessageStreamDeltaEvent(
                        segment=ToolCallDetailSegment(
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            partial_arguments=event.delta,
                            index=self._get_segment_index(
                                segment_indexes,
                                segment_type="tool",
                                item_key=f"{call_id}:{event.output_index}",
                            ),
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseFunctionCallArgumentsDoneEvent):
                    function_call = function_calls.get(event.item_id)
                    if function_call is None:
                        continue
                    call_id, tool_name = function_call
                    completed_function_calls.add(event.item_id)
                    yield MessageStreamCompleteEvent(
                        segment=ToolSegment(
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            arguments=parse_tool_arguments(event.arguments),
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseOutputItemDoneEvent) and isinstance(
                    event.item, ResponseFunctionToolCall
                ):
                    if event.item.id and event.item.id in completed_function_calls:
                        continue
                    yield MessageStreamCompleteEvent(
                        segment=ToolSegment(
                            tool_call_id=event.item.call_id,
                            tool_name=event.item.name,
                            arguments=parse_tool_arguments(event.item.arguments),
                        ),
                        index=_next_event_index(),
                    )
                elif isinstance(event, ResponseCompletedEvent):
                    if event.response.usage is None:
                        continue
                    usage = event.response.usage
                    yield MessageStreamCompleteEvent(
                        segment=UsageSegment(
                            input_tokens=usage.input_tokens,
                            output_tokens=usage.output_tokens,
                            total_tokens=usage.total_tokens,
                            cached_tokens=usage.input_tokens_details.cached_tokens,
                            reasoning_tokens=usage.output_tokens_details.reasoning_tokens,
                        ),
                        index=_next_event_index(),
                    )
                    if event.response.status is not None:
                        yield MessageStreamCompleteEvent(
                            segment=StopSegment.from_raw_reason(event.response.status),
                            index=_next_event_index(),
                        )
                elif isinstance(event, ResponseErrorEvent):
                    raise RuntimeError(event.message)
                elif isinstance(event, ResponseFailedEvent):
                    raise RuntimeError(f"OpenAI responses stream failed with status {event.response.status}")


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
            completion_messsages.append(
                ChatCompletionAssistantMessageParam(
                    role="assistant", content=assistant_segments, tool_calls=tools_calls
                )
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
    from openai import NotFoundError

    load_dotenv()

    async def _test_stream() -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Set OPENAI_API_KEY before running _test_stream(). \
                This helper exercises the Responses API stream endpoint used by OpenAIAPI.stream()."
            )

        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("OPENAI_STREAM_TEST_MODEL", "gpt-5.4")

        openai_api = OpenAIAPI(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

        print("Streaming response:\n", end="", flush=True)
        try:
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
        except NotFoundError as exc:
            raise RuntimeError(
                f"{base_url} does not expose the OpenAI Responses API stream endpoint used by OpenAIAPI.stream(). \
                Use a Responses-compatible OPENAI_BASE_URL, \
                or switch to the provider-specific adapter for DeepSeek/OpenRouter-style chat.completions streaming."
            ) from exc

        print()

    asyncio.run(_test_stream())
