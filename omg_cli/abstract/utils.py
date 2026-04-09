from collections.abc import Sequence

from omg_cli.types.message import Message, TextSegment

type Messages = Sequence[Message] | Message | TextSegment | str


def to_messages(messages: Messages) -> Sequence[Message]:
    """Convert various input types to a sequence of Message objects."""
    if isinstance(messages, str):
        return [Message(role="user", name="user", content=[TextSegment(text=messages)])]
    elif isinstance(messages, TextSegment):
        return [Message(role="user", name="user", content=[messages])]
    elif isinstance(messages, Message):
        return [messages]
    else:
        return messages
