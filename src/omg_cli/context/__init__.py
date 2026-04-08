"""ChatContext for managing chat sessions with LLM providers."""

from collections.abc import AsyncIterator, Callable, Sequence
import copy
from datetime import UTC, datetime
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from src.omg_cli.abstract import ChatAdapter
from src.omg_cli.config import SessionMetadata, SessionStorage, get_config_manager
from src.omg_cli.context.command import CommandProtocol
from src.omg_cli.context.event_manager import EventManager
from src.omg_cli.context.mcp_manager import MCPManagerProtocol
from src.omg_cli.context.tool_manager import ToolConfirmationDecision, ToolManagerProtocol
from src.omg_cli.log import logger
from src.omg_cli.tool.todo import TodoProtocol
from src.omg_cli.tool.tools import TOOL_LIST
from src.omg_cli.types.event import (
    BaseEvent,
    SessionErrorEvent,
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

# Reserved tokens for context window safety margin
RESERVED_TOKENS = 50_000

# Number of recent message pairs to keep during compaction
RECENT_MESSAGES_TO_KEEP = 4

from src.omg_cli.prompts import COMPACT_MD

type ListenerRegistration = Callable[..., None | AsyncIterator[None]]


class Notifier:
    def __init__(self, context: "ChatContext") -> None:
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


class ChatContext(CommandProtocol, ToolManagerProtocol, MCPManagerProtocol, TodoProtocol):
    """Context for managing a chat session with an LLM provider.

    Combines tool management (ToolManagerProtocol) and todo management (TodoProtocol)
    to provide a complete chat context with planning capabilities.

    Example:
        context = ChatContext(provider=adapter, system_prompt="You are a helpful assistant.")
        await context.send("Hello!")

        # Enable planning mode for todo management
        context.set_planning(True)
    """

    skills: list[SkillRef]

    def __init__(
        self,
        *,
        provider: ChatAdapter,
        system_prompt: str,
        tools: Sequence[Tool[Any]] | None = None,
        messages: Sequence[Message] | None = None,
        skills: list[SkillRef] | None = None,
        session_id: str | None = None,
    ) -> None:
        # Initialize protocols
        CommandProtocol.__init__(self)
        ToolManagerProtocol.__init__(self)
        MCPManagerProtocol.__init__(self)
        TodoProtocol.__init__(self)

        # Session storage
        self._session_storage = SessionStorage()

        # Core attributes
        self.session_id = session_id or str(uuid4())
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
        self.thinking_mode = False

        # MCP mode: when enabled, MCP server tools are available
        self.mcp_mode = True

        # Anthropic skills to enable for this session
        self.skills: list[SkillRef] = list(skills or [])

        self.logger = Notifier(self)

        # Interrupt flag for stopping LLM output
        self._interrupt_requested = False

        # Message queue for pending user inputs during LLM thinking
        self._message_queue: list[str] = []
        self._is_thinking: bool = False

        # Setup tools
        self._setup_tools(tools or [])
        self._setup_default_tools()
        self._register_compact_tool()

        # Initialize session metadata if not loading existing
        self._session_metadata: SessionMetadata | None = None

    def _register_compact_tool(self) -> None:
        class CompactContextParams(BaseModel):
            keep_recent: int = Field(
                default=RECENT_MESSAGES_TO_KEEP,
                description="Number of recent messages to keep without summarization",
            )

        compact_tool = Tool(
            name="compact_context",
            description=(
                "Compact the conversation context by summarizing older messages. "
                "Use this when the context is getting too long. "
                "Preserves recent messages and summarizes older ones into a structured format."
            ),
            params_model=CompactContextParams,
            confirm=False,
            tags=frozenset({"context", "system"}),
        )
        compact_tool.bind(self._compact_context_impl)
        self.register_tool(compact_tool)

    async def _compact_context_impl(self, keep_recent: int = RECENT_MESSAGES_TO_KEEP) -> str | None:
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

        result_msg = (
            f"Context compacted: {old_count} -> {len(self.messages)} messages. "
            f"Summarized {len(messages_to_summarize)}, kept {len(recent_messages)} recent."
        )
        await self.logger.success(result_msg)
        logger.success(result_msg)

        return summary_text

    def _setup_default_tools(self) -> None:
        """Register default tools from the tool module."""
        # Delayed import to avoid circular import

        for tool in TOOL_LIST:
            self.register_tool(tool)

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

    @property
    def command_registry(self) -> CommandProtocol:
        """Get the command registry (returns self as CommandProtocol)."""
        return self

    async def _update_max_context_size(self) -> None:
        try:
            max_context = await self.provider.context_length()
            if max_context > 0:
                self.token_usage.max_context_size = max_context
            self.token_usage.initial_context_size = True
        except Exception:
            # Keep default if provider doesn't support context_length
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
        self.session_id = str(uuid4())
        self._session_metadata = None

        await self._update_max_context_size()
        await self._emit(SessionResetEvent())

    def interrupt(self) -> None:
        """Request to interrupt the current LLM output stream."""
        self._interrupt_requested = True

    def _clear_interrupt(self) -> None:
        """Clear the interrupt flag."""
        self._interrupt_requested = False

    @property
    def pending_messages(self) -> list[str]:
        """Get the pending message queue (messages entered while LLM is thinking)."""
        return self._message_queue

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

        # Set thinking flag
        self._is_thinking = True

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
                await self._append_message(assistant_msg)

                for tool_call in round_tool_calls:
                    tool_result_message = await self._run_single_tool_call(tool_call)

                    current_conversation_round.append(tool_result_message)

                    response_messages.append(tool_result_message)

                    await self._append_message(tool_result_message)

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
                await self._append_message(assistant_msg)

        # Clear thinking flag
        self._is_thinking = False

        return response_messages, len(tool_calls) > 0

    async def send(
        self,
        user_input: str | list[str],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Send user message(s) and get assistant response.

        Args:
            user_input: User text input(s) to send
            system_prompt: Optional system prompt override
            **kwargs: Additional arguments for the provider
        """
        # Normalize to list of strings
        texts = [user_input] if isinstance(user_input, str) else user_input
        if not texts:
            return

        if not self.token_usage.initial_context_size:
            await self._update_max_context_size()

        # Build and append all user messages
        for text in texts:
            msg = Message(role="user", content=[TextSegment(text=text)])
            await self._append_message(msg)

        # Clear interrupt flag at the start of each send
        self._clear_interrupt()

        round_num = 0
        while True:
            await self.logger.debug(f"Assistant request started: {self.provider.model_name}")
            logger.debug(f"Current token usage before request: {self.token_usage}")

            provider_kwargs = dict(kwargs)
            max_tokens = provider_kwargs.pop("max_tokens", None)

            assistant_messages, tool_calls = await self.thinking(
                system_prompt=system_prompt or self.system_prompt,
                messages=self.messages,
                tools=self.tools,
                max_tokens=max_tokens,
                **provider_kwargs,
            )

            for message in assistant_messages:
                logger.debug(f"Assistant message received: {message}")

            # If interrupted or no tool calls, thinking is completed, break the loop
            if self._interrupt_requested or not tool_calls:
                return None

            round_num += 1

            await self.logger.debug(f"Round completed: {round_num}")

    async def _run_single_tool_call(self, tool_call: ToolCall) -> Message:
        """Run a single tool call and build the tool message."""
        tool_name = tool_call.function.name
        await self.logger.debug(f"Tool call started: {tool_name}")

        tool = self._tool_map.get(tool_name)
        if tool is None:
            error_message = f"Tool '{tool_name}' is not registered"
            await self._emit(SessionErrorEvent(error=error_message))
            return self._build_tool_message(tool_call, {"error": error_message})

        if tool.confirm:
            decision = await self._confirm_tool_call(tool_call, tool)
            if not decision.approved:
                rejection = {"error": "Tool call rejected by user"}
                if decision.reason:
                    rejection["reason"] = decision.reason
                if decision.next_steps:
                    rejection["next_steps"] = decision.next_steps
                await self.logger.warn(f"Tool call rejected: {tool_name}")
                return self._build_tool_message(tool_call, rejection)

        try:
            result = await tool(**tool_call.function.arguments)
        except ToolError as exc:
            # Tool execution failed - return error to LLM for handling
            error_message = str(exc)
            await self._emit(SessionErrorEvent(error=f"Tool '{tool_name}' failed: {error_message}"))
            return self._build_tool_message(tool_call, {"error": error_message})
        except Exception as exc:
            # Unexpected error - log and return to LLM
            error_message = f"Tool '{tool_name}' failed unexpectedly: {exc}"
            await self._emit(SessionErrorEvent(error=error_message))
            return self._build_tool_message(tool_call, {"error": str(exc)})

        await self.logger.debug(f"Tool call completed: {tool_name}")
        return self._build_tool_message(tool_call, result)

    def _build_tool_message(self, tool_call: ToolCall, result: Any) -> Message:
        """Build a tool message from a tool call and result."""
        if result is None:
            _serialize_tool_result = ""
        if isinstance(result, str):
            _serialize_tool_result = result
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

    async def _append_message(self, message: Message) -> None:
        """
        Append a message to the context and display it.
        Also persists the message to storage.
        """
        self.messages.append(message)
        self.display_messages.append(message)

        # Persist message to storage
        self._persist_message(message)

        await self._emit(SessionMessageEvent(message=message))

    def _persist_message(self, message: Message) -> None:
        """Persist a message to storage and update metadata."""
        try:
            # Append message to jsonl
            self._session_storage.append_message(self.session_id, message)

            # Update metadata
            if self._session_metadata is None:
                self._session_metadata = SessionMetadata(
                    session_id=self.session_id,
                    created_at=datetime.now(tz=UTC),
                    updated_at=datetime.now(tz=UTC),
                    model_name=self.provider.model_name,
                )
            self._session_metadata.updated_at = datetime.now(tz=UTC)

            # Update title if this is the first user message
            if message.role == "user" and self._session_metadata.title is None:
                self._session_metadata.title = self._session_storage.generate_title(self.messages)

            # Save metadata
            self._session_storage.save_metadata(self._session_metadata)
        except Exception:
            # Silently ignore storage errors to not disrupt the chat flow
            pass

    def load_session(self, session_id: str) -> bool:
        """Load a session from storage.

        Returns True if session was found and loaded.
        """
        try:
            metadata = self._session_storage.load_metadata(session_id)
            if metadata is None:
                return False

            messages = self._session_storage.load_messages(session_id)

            self.session_id = session_id
            self._session_metadata = metadata
            self.messages = messages
            self.display_messages = list(messages)

            return True
        except Exception:
            return False

    def list_saved_sessions(self) -> list[SessionMetadata]:
        """List all saved sessions."""
        return self._session_storage.list_sessions()

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from storage."""
        return self._session_storage.delete(session_id)

    async def switch_model(self, model_name: str) -> bool:
        model_config = self.config_manager.get_model(model_name)

        if model_config is None:
            await self.logger.error(f"未找到模型: {model_name}")
            return False

        try:
            # Create new adapter from config
            adapter = model_config.create_adapter()
            # Update provider
            self.provider = adapter
            # If new model doesn't support thinking, disable it
            if not adapter.thinking_supported:
                self.thinking_mode = False
            await self.logger.success(f"已切换到模型: {model_name}")
            return True
        except Exception as exc:
            await self.logger.error(f"切换模型失败: {exc}")
            return False

    async def _emit(self, event: BaseEvent) -> None:
        """Emit an event through the event manager."""
        await self._event_manager.publish(event)

    def register_event_handler(self, event_type: type, handler: Callable) -> None:
        """Register an event handler for a specific event type."""
        self._event_manager.register(event_type, handler)


__all__ = [
    "ChatContext",
    "Notifier",
    "SessionMetadata",
    "ToolConfirmationDecision",
    "ToolManagerProtocol",
]
