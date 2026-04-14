from types import SimpleNamespace

from omg_cli import __main__ as main_mod


class _FakeAdapterManager:
    def __init__(self) -> None:
        self.default_adapter = object()

    def get_adapter(self, model_name: str):
        raise ValueError(model_name)

    def list_adapters(self):
        return ["demo"]


def test_main_routes_to_gui(monkeypatch) -> None:
    calls = {"gui": 0, "tui": 0}

    monkeypatch.setattr(main_mod, "load_dotenv", lambda: None)
    monkeypatch.setattr(main_mod, "get_adapter_manager", lambda: _FakeAdapterManager())
    monkeypatch.setattr(main_mod, "render_system_prompt", lambda _cwd: "system")

    def _fake_chat_context(*, provider, system_prompt):
        return SimpleNamespace(provider=SimpleNamespace(model_name="fake-model"))

    monkeypatch.setattr(main_mod, "ChatContext", _fake_chat_context)

    def _fake_run_gui(*, context, channel, debug):
        calls["gui"] += 1
        assert channel is False
        assert debug is False

    def _fake_run_terminal(context, channel):
        calls["tui"] += 1

    monkeypatch.setattr(main_mod, "run_gui", _fake_run_gui)
    monkeypatch.setattr(main_mod, "run_terminal", _fake_run_terminal)

    main_mod.main(["--gui"])

    assert calls["gui"] == 1
    assert calls["tui"] == 0
