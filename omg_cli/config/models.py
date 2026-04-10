from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from omg_cli.abstract import ChatAdapter
from omg_cli.abstract.anthropic import AnthropicAPI
from omg_cli.abstract.deepseek import DeepSeekAPI
from omg_cli.abstract.openai import OpenAIAPI
from omg_cli.abstract.openai_legacy import OpenAILegacy

ProviderType = Literal["openai", "anthropic", "deepseek", "openai_legacy"]


class ModelConfig(BaseModel):
    """Configuration for a single model/provider.

    API keys are stored as SecretStr to prevent accidental exposure in logs.
    The actual security relies on filesystem permissions (0o600).
    """

    name: str
    provider: ProviderType
    model: str  # Model name like "gpt-4", "claude-3-opus", etc.
    base_url: str
    api_key: SecretStr = Field(description="API key (protected by filesystem permissions)")
    thinking_supported: bool = False
    skills: list[str] = Field(default_factory=list, description="Anthropic skill IDs to enable by default")

    def get_api_key(self) -> str:
        """Get the actual API key value."""
        return self.api_key.get_secret_value()

    def create_adapter(self) -> ChatAdapter:
        api_key = self.get_api_key()

        match self.provider:
            case "openai":
                return OpenAIAPI(
                    api_key=api_key,
                    model=self.model,
                    base_url=self.base_url,
                )
            case "anthropic":
                return AnthropicAPI(
                    api_key=api_key,
                    model=self.model,
                    base_url=self.base_url,
                    thinking_supported=self.thinking_supported,
                    skills=self.skills,
                )
            case "deepseek":
                return DeepSeekAPI(
                    api_key=api_key,
                    model=self.model,
                    base_url=self.base_url,
                )
            case "openai_legacy":
                return OpenAILegacy(
                    api_key=api_key,
                    model=self.model,
                    base_url=self.base_url,
                )
            case _:
                # Default to OpenAI compatible
                return OpenAILegacy(
                    api_key=api_key,
                    model=self.model,
                    base_url=self.base_url,
                )

    def to_storage_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage.

        Note: This returns the plaintext API key for storage.
        Security is enforced by filesystem permissions (0o600).
        """
        data = self.model_dump()
        # SecretStr is serialized as plaintext for storage
        # The file permissions (0o600) provide the actual protection
        data["api_key"] = self.get_api_key()
        return data

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        """Create from storage dictionary."""
        return cls.model_validate(data)


class RoleConfig(BaseModel):
    name: str
    desc: str = ""
    adapter_name: str


class ChannelConfig(BaseModel):
    project_path: str
    default_role: str | None = None
    assigned_roles: list[str] = Field(default_factory=list)


class UserConfig(BaseModel):
    default_model: str | None = None
