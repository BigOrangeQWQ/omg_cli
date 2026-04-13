from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, DirectoryPath, Field

from omg_cli.types.message import Message

if TYPE_CHECKING:
    from omg_cli.abstract import ChatAdapter


class ThreadStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = " running"
    REVIEW = "review"
    DONE = "done"
    ERROR = "error"
    STALLED = "stalled"


RoleActivityType = Literal["thinking", "tool_call", "status", "error", "stream", "message"]


class Role(BaseModel):
    name: str
    desc: str
    personal_space: DirectoryPath
    adapter_name: str

    @property
    def adapter(self) -> ChatAdapter:
        from omg_cli.config.adapter_manager import get_adapter_manager

        return get_adapter_manager().get_adapter(self.adapter_name)


class RoleActivityRecord(BaseModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    activity_type: RoleActivityType
    content: str


class Thread(BaseModel):
    id: int
    title: str
    description: str = ""
    messages: list[Message] = Field(default_factory=list)
    assigned_role_names: list[str] = Field(default_factory=list)
    reviewer_role_names: list[str] = Field(default_factory=list)
    status: ThreadStatus = ThreadStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    parent_thread_id: int | None = None
    role_activities: dict[str, list[RoleActivityRecord]] = Field(default_factory=dict)


class Channel(BaseModel):
    name: str
    roles: list[Role]
    threads: list[Thread] = Field(default_factory=list)
    default_role_name: str | None = None

    def next_thread_id(self) -> int:
        if not self.threads:
            return 1
        return max(t.id for t in self.threads) + 1

    def get_role(self, name: str) -> Role | None:
        for role in self.roles:
            if role.name == name:
                return role
        return None

    def add_thread(
        self,
        title: str,
        *,
        description: str = "",
        assigned_role_names: list[str] | None = None,
        reviewer_role_names: list[str] | None = None,
        parent_thread_id: int | None = None,
    ) -> Thread:
        thread = Thread(
            id=self.next_thread_id(),
            title=title,
            description=description,
            assigned_role_names=list(assigned_role_names or []),
            reviewer_role_names=list(reviewer_role_names or []),
            parent_thread_id=parent_thread_id,
        )
        self.threads.append(thread)
        return thread
