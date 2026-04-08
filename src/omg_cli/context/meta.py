"""MetaContext for managing chat sessions with LLM providers."""

from collections.abc import AsyncIterator, Callable, Sequence
import copy
import json
from typing import Any
from uuid import uuid4

from src.omg_cli.abstract import ChatAdapter
from src.omg_cli.config import SessionMetadata, SessionStorage, get_config_manager
from src.omg_cli.context.command import CommandProtocol
from src.omg_cli.context.event_manager import EventManager
from src.omg_cli.context.mcp_manager import MCPManagerProtocol
from src.omg_cli.context.tool_manager import ToolManagerProtocol
from src.omg_cli.log import logger
from src.omg_cli.prompts import COMPACT_MD
from src.omg_cli.tool.todo import TodoProtocol
from src.omg_cli.tool.tools import TOOL_LIST
from src.omg_cli.types.event import (
    BaseEvent,
    SessionMessageEvent,
    SessionResetEvent,
    SessionStatusEvent,
    SessionStreamCompletedEvent,
    SessionStreamDeltaEvent,
    StatusLevel,
)
from src.omg_cli.types.message import (
    Message,
    MessageSegment,
    MessageStreamCompleteEvent,
    MessageStreamDeltaEvent,
    StopSegment,
    TextSegment,
    ThinkDetailSegment,
    ThinkSegment,
    ToolCall,
    ToolResultSegment,
    ToolSegment,
    UsageSegment,
)
from src.omg_cli.types.skill import SkillRef
from src.omg_cli.types.tool import Tool, ToolError
from src.omg_cli.types.usage import TokenUsage

SUB_ROUNDS_LIMIT = 10
RESERVED_TOKENS = 50_000
RECENT_MESSAGES_TO_KEEP = 4


type ListenerRegistration = Callable[..., None | AsyncIterator[None]]


class Notifier:
    def __init__(self, context: "MetaContext") -> None:
        self._context = context

    async def _emit(self, message: str, level: StatusLevel) -> None:
        # Log to standard logger based on level
        if level <= StatusLevel.DEBUG:
            logger.debug(message)
        elif level <= StatusLevel.INFO:
            logger.info(message)
        elif level <= StatusLevel.SUCCESS:
            logger.info(message)  # SUCCESS maps to INFO for standard logger
        elif level <= StatusLevel.WARN:
            logger.warning(message)
        else:
            logger.error(message)
        await self._context._emit(SessionStatusEvent(detail=message, level=level))

    async def debug(self, message: str) -> None:
        await self._emit(message, StatusLevel.DEBUG)

    async def info(self, message: str) -> None:
        await self._emit(message, StatusLevel.INFO)

    async def success(self, message: str) -> None:
        await self._emit(message, StatusLevel.SUCCESS)

    async def warn(self, message: str) -> None:
        await self._emit(message, StatusLevel.WARN)

    async def error(self, message: str) -> None:
        await self._emit(message, StatusLevel.ERROR)


class MetaContext(CommandProtocol, ToolManagerProtocol, MCPManagerProtocol, TodoProtocol):
    """
    Base context for managing a chat session with an LLM provider.

    Provides common infrastructure for message management, tool execution,
    event publishing, and session persistence. Subclasses (ChatContext,
    RoleContext) customize interaction patterns while reusing the core loop.
    """

    skills: list[SkillRef]
    messages: list[Message]
    display_messages: list[Message]
    session_id: str

    def __init__(
        self,
        *,
        provider: ChatAdapter,
        system_prompt: str,
        tools: Sequence[Tool[Any]] | None = None,
        messages: Sequence[Message] | None = None,
        skills: list[SkillRef] | None = None,
    ) -> None:
        # Initialize protocols
        CommandProtocol.__init__(self)
        ToolManagerProtocol.__init__(self)
        MCPManagerProtocol.__init__(self)
        TodoProtocol.__init__(self)

        # Session storage
        self._session_storage = SessionStorage()

        # Core attributes
        self.session_id = uuid4().hex
        self.provider = provider
        self.system_prompt = system_prompt
        self.messages: list[Message] = list(messages or [])
        # Display messages for UI - separated thinking steps for better visualization
        self.display_messages: list[Message] = list(messages or [])

        # Event manager for pub/sub (internal)
        self._event_manager = EventManager()

        # Token usage tracking
        self.token_usage = TokenUsage()
        self.config_manager = get_config_manager()

        # Planning mode: when enabled, todo.txt tools are available
        self.planning_mode = False

        # Thinking mode: when enabled, LLM will show thinking process
        self.thinking_mode = True

        # MCP mode: when enabled, MCP server tools are available
        self.mcp_mode = True

        # Anthropic skills to enable for this session
        self.skills: list[SkillRef] = list(skills or [])

        self.logger = Notifier(self)

        # Interrupt flag for stopping LLM output
        self._interrupt_requested = False

        # Message queue for pending user inputs during LLM thinking
        self._message_queue: list[Message] = []

        # Setup tools
        self._setup_tools(tools or [])
        for tool in TOOL_LIST:
            self.register_tool(tool)

        # Initialize session metadata if not loading existing
        self._session_metadata: SessionMetadata | None = None

    @property
    def tools(self) -> list[Tool[Any]]:
        """Get all available tools for LLM calls.

        Returns base tools plus MCP tools from connected servers (when mcp_mode is on),
        and todo tools when planning mode is enabled.
        """
        all_tools = self.list_tools()

        # Add MCP tools from all connected servers when mcp_mode is enabled
        if self.mcp_mode:
            mcp_tools: list[Tool[Any]] = []
            for client in self._mcp_clients.values():
                mcp_tools.extend(client.to_internal_tools())
            all_tools = all_tools + mcp_tools

        if self.planning_mode:
            return all_tools + self.todo_tools()
        return all_tools

    async def _initial_context_size(self) -> None:
        if self.token_usage.initial_context_size:
            return
        self.token_usage.initial_context_size = True
        try:
            max_context = await self.provider.context_length()
            if max_context > 0:
                self.token_usage.max_context_size = max_context
        except Exception:
            pass

    async def reset(self) -> None:
        """Reset the chat context, clearing messages and token usage.

        This creates a new session, preserving the old one in storage.
        """
        self.messages.clear()
        self.display_messages.clear()
        self._session_approve_all = False
        self.token_usage = TokenUsage()  # Reset token usage
        self._message_queue.clear()  # Clear pending message queue

        # Generate new session ID for new conversation
        self.session_id = uuid4().hex
        self._session_metadata = None

        await self._initial_context_size()

        await self._emit(SessionResetEvent())

    def interrupt(self) -> None:
        self._interrupt_requested = True

    async def _emit(self, event: BaseEvent) -> None:
        """
        Publish an event to the event manager and log it if it's a status event.
        """
        await self._event_manager.publish(event)

    def register_event_handler(self, event_type: type, handler: Callable) -> None:
        """Register an event handler for a specific event type."""
        self._event_manager.register(event_type, handler)

    async def append(self, message: Message) -> None:
        """
        Append a message to the context and display it.

        Also persists the message to storage.
        """
        # Persist message to storage
        self._session_storage.append_message(self.session_id, message)

        self.messages.append(message)
        self.display_messages.append(message)

        await self._emit(SessionMessageEvent(message=message))

    async def compact_context(self, keep_recent: int = RECENT_MESSAGES_TO_KEEP) -> str | None:
        if len(self.messages) < keep_recent + 1:
            return "Not enough messages to compact"

        logger.info(f"Compacting context: {len(self.messages)} messages, keeping {keep_recent} recent")

        # Split messages: older to summarize, recent to keep
        messages_to_summarize = self.messages[:-keep_recent]
        recent_messages = self.messages[-keep_recent:]

        # Build context text for summarization
        context_parts = []
        for msg in messages_to_summarize:
            role_display = f"assistant ({msg.name})" if msg.name else msg.role
            content_text = " ".join(str(segment) for segment in msg.content)
            context_parts.append(f"**{role_display}**: {content_text}\n")
        context_text = "\n".join(context_parts)

        try:
            summary_message = await self.provider.chat(
                system_prompt="",
                messages=COMPACT_MD.format(
                    CONTEXT=context_text,
                ),
                tools=[],
            )
            # Extract text from message content
            summary_text = summary_message.text
        except Exception as exc:
            logger.error(f"LLM summarization failed: {exc}")
            raise ToolError(f"Context compaction failed: {exc}")

        # New messages: summary + recent messages
        new_messages: list[Message] = [summary_message, *recent_messages]

        old_count = len(self.messages)
        self.messages = new_messages
        self.display_messages = list(new_messages)

        # Persist compacted messages to disk
        self._session_storage.save_messages(self.session_id, new_messages)

        result_msg = (
            f"Context compacted: {old_count} -> {len(self.messages)} messages. "
            f"Summarized {len(messages_to_summarize)}, kept {len(recent_messages)} recent."
        )
        await self.logger.success(result_msg)
        logger.success(result_msg)

        return summary_text

    async def thinking(
        self,
        system_prompt: str,
        messages: Sequence[Message],
        tools: list[Tool[Any]] | None = None,
        max_tokens: int | None = None,
        sub_rounds_limit: int = SUB_ROUNDS_LIMIT,
    ) -> tuple[list[Message], bool]:
        """
        loop is core logic for thinking, it will keep sending messages to provider until:

        1) no tool calls in response, which means thinking is completed, or
        2) stop signal received from provider, or
        3) sub_rounds_limit reached to avoid infinite loop
        """

        if not tools:
            tools = []

        total_rounds = 0
        # Make a mutable copy of messages to append thinking steps and tool call results
        current_conversation_round: list[Message] = list(copy.deepcopy(messages))
        response_messages: list[Message] = []

        tool_calls: list[ToolCall] = []
        thinking_content = ""
        thinking_signature: str | None = None

        stop_this_round = False
        logger.debug(f"[_execute_thinking] START, messages_count={len(current_conversation_round)}")
        while total_rounds < sub_rounds_limit and not stop_this_round:
            total_rounds += 1
            logger.debug(f"[_execute_thinking] round={total_rounds}")

            if len(current_conversation_round) > 1:
                last_message = current_conversation_round[-1]
                # if self.thinking_mode != True, we alaways receive TextSegment, in_thinking is always False
                if last_message.in_thinking:
                    current_conversation_round.pop()
                    current_conversation_round.append(
                        Message(
                            role="assistant",
                            content=[ThinkSegment(thought_process=thinking_content, signature=thinking_signature)],
                            tool_calls=tool_calls,
                        )
                    )

            round_segments: list[MessageSegment] = []
            round_tool_calls: list[ToolCall] = []
            event_count = 0
            complete_event_count = 0
            # Reset thinking_content and thinking_signature for this round to avoid duplication
            current_thinking_content = ""
            current_thinking_signature: str | None = None

            streaming: AsyncIterator[MessageStreamDeltaEvent | MessageStreamCompleteEvent] = self.provider.stream(
                system_prompt=system_prompt,
                messages=current_conversation_round,
                tools=tools,
                max_tokens=max_tokens,
                thinking=True if self.thinking_mode else False,
                skills=self.skills if self.skills else None,
            )
            async for event in streaming:
                # Check for interrupt request
                if self._interrupt_requested:
                    logger.debug("[_execute_thinking] interrupted by user")
                    stop_this_round = True
                    break
                event_count += 1
                if isinstance(event, MessageStreamDeltaEvent):
                    await self._emit(SessionStreamDeltaEvent(stream_event=event))
                    match event.segment:
                        case ThinkDetailSegment(thought_process=text):
                            current_thinking_content += text
                            thinking_content += text
                if isinstance(event, MessageStreamCompleteEvent):
                    complete_event_count += 1
                    await self._emit(SessionStreamCompletedEvent(stream_event=event))
                    match event.segment:
                        case ToolSegment() as tool_call_segment:
                            round_tool_calls.append(tool_call_segment.to_tool_call())
                            round_segments.append(tool_call_segment)
                        case ThinkSegment() as segment:
                            round_segments.append(segment)
                            # ThinkSegment already contains the complete thinking content
                            # Clear current_thinking_content to avoid duplication in tool call handling
                            current_thinking_content = ""
                            current_thinking_signature = segment.signature
                        case TextSegment() as segment:
                            round_segments.append(segment)
                        case UsageSegment() as usage:
                            # Accumulate token usage for this thinking round
                            await self.logger.debug(
                                f"Token usage update from stream: input={usage.input_tokens}, \
                                output={usage.output_tokens}"
                            )
                            self.token_usage.grow_by_usage(usage)
                        case StopSegment(reason=reason):
                            if reason == "tool_calls":
                                continue
                            stop_this_round = True
                        case _:
                            stop_this_round = True

            logger.debug(
                f"[_execute_thinking] round={total_rounds} done, events={event_count},\
                    complete_events={complete_event_count}, round_segments={len(round_segments)},\
                        round_tool_calls={len(round_tool_calls)}"
            )

            if round_tool_calls:
                # If we have accumulated thinking content but no ThinkSegment in round_segments,
                # prepend the thinking content as a ThinkSegment for context continuity
                if current_thinking_content and not any(isinstance(s, ThinkSegment) for s in round_segments):
                    round_segments.insert(
                        0,
                        ThinkSegment(
                            thought_process=current_thinking_content,
                            signature=current_thinking_signature,
                        ),
                    )

                assistant_msg = Message(
                    role="assistant",
                    name=self.provider.model_name,
                    content=round_segments,
                    tool_calls=round_tool_calls,
                )

                response_messages.append(assistant_msg)
                # Sub round message
                current_conversation_round.append(assistant_msg)
                # History message for display (without tool calls to avoid confusion)
                await self.append(assistant_msg)

                for tool_call in round_tool_calls:
                    tool_result_message = await self._run_single_tool_call(tool_call)

                    current_conversation_round.append(tool_result_message)

                    response_messages.append(tool_result_message)

                    await self.append(tool_result_message)

                    tool_calls.append(tool_call)
            elif round_segments:
                # Pure text / thinking response with no tool calls
                assistant_msg = Message(
                    role="assistant",
                    name=self.provider.model_name,
                    content=round_segments,
                )
                response_messages.append(assistant_msg)
                current_conversation_round.append(assistant_msg)
                await self.append(assistant_msg)

        return response_messages, len(tool_calls) > 0

    async def round(self, **kwargs) -> None:
        """
        Core loop for a single round of interaction with the LLM provider.
        """
        round_num = 0

        self._interrupt_requested = False

        while True:
            await self.logger.debug(f"Assistant request started: {self.provider.model_name}")
            logger.debug(f"Current token usage before request: {self.token_usage}")

            provider_kwargs = dict(kwargs)
            max_tokens = provider_kwargs.pop("max_tokens", None)

            _assistant_messages, tool_calls = await self.thinking(
                system_prompt=self.system_prompt,
                messages=self.messages,
                tools=self.tools,
                max_tokens=max_tokens,
                **provider_kwargs,
            )

            if self._message_queue:
                # If we have pending user messages, append them to the context for the next round
                for msg in self._message_queue:
                    await self.append(msg)
                self._message_queue.clear()
                continue

            # If interrupted or no tool calls, thinking is completed, break the loop
            if self._interrupt_requested or not tool_calls:
                return None

            round_num += 1
            await self.logger.debug(f"Round completed: {round_num}")

    async def send(
        self,
        user_input: str | list[str],
    ) -> None:
        """
        Send user message(s) to the message queue.
        If currently in a thinking process, messages will be queued and sent after completion.
        """
        # Normalize to list of strings
        texts = [user_input] if isinstance(user_input, str) else user_input
        if not texts:
            return

        if not self.token_usage.initial_context_size:
            await self._initial_context_size()

        for text in texts:
            self._message_queue.append(Message(role="user", content=[TextSegment(text=text)]))

    async def _run_single_tool_call(self, tool_call: ToolCall) -> Message:
        raise NotImplementedError


def tool_call_to_message(tool_call: ToolCall, result: Any) -> Message:
    if result is None:
        _serialize_tool_result = ""
    elif isinstance(result, str):
        _serialize_tool_result = result
    else:
        try:
            _serialize_tool_result = json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            _serialize_tool_result = str(result)

    return Message(
        role="tool",
        name=tool_call.function.name,
        content=[
            ToolResultSegment(
                tool_call_id=tool_call.id,
                tool_name=tool_call.function.name,
                content=_serialize_tool_result,
                is_error=isinstance(result, dict) and "error" in result,
            ),
        ],
    )


__all__ = [
    "MetaContext",
    "Notifier",
]
