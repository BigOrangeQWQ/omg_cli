from pydantic import BaseModel, computed_field

from src.omg_cli.types.message import UsageSegment


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    # Current context token count (tracks the conversation size)
    context_tokens: int = 0

    # Maximum context window size (from model's context_length)
    # oneshot request input tokens + expected output tokens should be <= max_context_size
    max_context_size: int = 100000  # Default is 100k tokens if unknown

    initial_context_size: bool = False

    def grow(self, input_tokens: int, output_tokens: int) -> None:
        """Update token usage with new API call."""
        self.input_tokens += input_tokens
        self.context_tokens += input_tokens
        self.output_tokens += output_tokens

    def grow_by_usage(self, usage: UsageSegment):
        self.grow(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    @computed_field
    @property
    def total_tokens(self) -> int:
        """Total tokens accumulated from all API calls (input + output)."""
        return self.input_tokens + self.output_tokens

    @computed_field
    @property
    def context_usage(self) -> float:
        if self.max_context_size <= 0:
            return 0.0
        return (self.context_tokens / self.max_context_size) * 100

    @computed_field
    @property
    def remaining_tokens(self) -> int:
        return self.max_context_size - self.context_tokens

    @computed_field
    @property
    def remaining_usage(self) -> float:
        if self.max_context_size <= 0:
            return 0.0
        return (self.remaining_tokens / self.max_context_size) * 100

    def __repr__(self) -> str:
        return (
            f"TokenUsage(input={self.input_tokens}, output={self.output_tokens}, "
            f"context={self.context_tokens}/{self.max_context_size}, "
            f"usage={self.context_usage:.1f}%)"
        )
