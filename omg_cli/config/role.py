"""Role manager built on top of ConfigManager."""

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any

import tomli_w

from omg_cli.config.constants import DEFAULT_CONFIG_DIR
from omg_cli.config.models import RoleConfig
from omg_cli.types.channel import Role


class RoleManager:
    """Manages role configurations independently from ConfigManager."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.config_file = self.config_dir / "config.toml"

    def _ensure_dir_exists(self) -> None:
        """Ensure config directory exists with secure permissions."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.chmod(0o700)

    def _load_toml(self) -> dict[str, Any]:
        """Load the main TOML config file if it exists."""
        if not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, "rb") as f:
                return tomllib.load(f)
        except Exception:
            return {}

    def _save_toml(self, data: dict[str, Any]) -> None:
        """Save the main TOML config file with secure permissions."""
        self._ensure_dir_exists()
        with open(self.config_file, "wb") as f:
            tomli_w.dump(data, f)
        self.config_file.chmod(0o600)

    def list_roles_config(self) -> list[RoleConfig]:
        """List all configured role definitions."""
        data = self._load_toml()
        roles: list[RoleConfig] = []
        roles_data = data.get("roles", {})
        if isinstance(roles_data, dict):
            for name, value in roles_data.items():
                role_data = dict(value) if isinstance(value, dict) else {}
                role_data["name"] = name
                try:
                    roles.append(RoleConfig.model_validate(role_data))
                except Exception:
                    continue
        return roles

    def save_roles_config(self, roles: list[RoleConfig]) -> None:
        """Save role configurations to TOML [roles.<name>] sections."""
        data = self._load_toml()
        if "roles" in data:
            del data["roles"]
        roles_data = {}
        for role in roles:
            roles_data[role.name] = role.model_dump()
        if roles_data:
            data["roles"] = roles_data
        self._save_toml(data)

    def add_role_config(self, role: RoleConfig) -> None:
        """Add or update a role configuration."""
        roles = self.list_roles_config()
        roles = [r for r in roles if r.name != role.name]
        roles.append(role)
        self.save_roles_config(roles)

    def get_role_config(self, name: str) -> RoleConfig | None:
        """Get a role configuration by name."""
        for r in self.list_roles_config():
            if r.name == name:
                return r
        return None

    def has_roles(self) -> bool:
        """Check if any roles are configured."""
        return len(self.list_roles_config()) > 0

    def list_roles(self) -> list[Role]:
        """List all instantiated roles."""
        roles: list[Role] = []
        for role_config in self.list_roles_config():
            role = self._instantiate_role(role_config)
            if role is not None:
                roles.append(role)
        return roles

    def get_role(self, name: str) -> Role | None:
        """Get an instantiated role by name."""
        role_config = self.get_role_config(name)
        if role_config is None:
            return None
        return self._instantiate_role(role_config)

    def _instantiate_role(self, role_config: RoleConfig) -> Role | None:
        personal_space = self.config_dir / "roles" / role_config.name
        personal_space.mkdir(parents=True, exist_ok=True)

        self_notes = personal_space / "SELF_NOTES.md"
        if not self_notes.exists():
            self_notes.touch()

        try:
            return Role(
                name=role_config.name,
                desc=role_config.desc,
                personal_space=personal_space,
                adapter_name=role_config.adapter_name,
            )
        except Exception:
            return None


@lru_cache(maxsize=1)
def get_role_manager() -> RoleManager:
    """Get the singleton RoleManager instance."""
    return RoleManager()
