"""Adapter manager for managing ChatAdapter instances."""

from functools import lru_cache

from omg_cli.abstract import ChatAdapter
from omg_cli.config.manager import ConfigManager


class AdapterManager:
    """Manager for ChatAdapter instances.

    Provides simple access to adapters created from configuration.
    """

    def __init__(self) -> None:
        self._config_manager = ConfigManager()
        self._cache: dict[str, ChatAdapter] = {}

    def list_adapters(self) -> list[str]:
        """List names of all configured models."""
        models = self._config_manager.list_models()
        return [m.name for m in models]

    def get_adapter(self, name: str) -> ChatAdapter:
        """Get adapter for a specific model.

        Args:
            name: Model name.

        Returns:
            ChatAdapter instance.

        Raises:
            ValueError: If model not found.
        """
        if name in self._cache:
            return self._cache[name]

        model_config = self._config_manager.get_model(name)
        if model_config is None:
            raise ValueError(f"Model '{name}' not found")

        adapter = model_config.create_adapter()
        self._cache[name] = adapter
        return adapter

    @property
    def default_adapter(self) -> ChatAdapter | None:
        """Get adapter for the default model, or None if not configured."""
        model_config = self._config_manager.get_default_model()
        if model_config is None:
            return None
        return self.get_adapter(model_config.name)


@lru_cache(maxsize=1)
def get_adapter_manager() -> AdapterManager:
    """Get the singleton AdapterManager instance."""
    return AdapterManager()
