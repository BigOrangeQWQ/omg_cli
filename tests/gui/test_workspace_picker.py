"""Tests for workspace picker GUI component."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from omg_cli.gui.workspace_picker import RecentDirCard, WorkspacePicker


class TestRecentDirCard:
    def test_card_shows_directory_name(self, qtbot):
        path = Path("/home/user/projects/test")
        card = RecentDirCard(path)
        qtbot.addWidget(card)

        assert card.title_label.text() == "test"
        assert str(path) in card.path_label.text()

    def test_click_emits_selected_signal(self, qtbot):
        path = Path("/home/user/projects/test")
        card = RecentDirCard(path)
        qtbot.addWidget(card)

        with qtbot.waitSignal(card.selected, timeout=1000) as blocker:
            card.open_button.click()

        assert blocker.args[0] == path


class TestWorkspacePicker:
    def test_picker_shows_without_recent_dirs(self, qtbot):
        with patch("omg_cli.gui.workspace_picker.get_config_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.list_recent_directories.return_value = []
            mock_get.return_value = mock_manager

            picker = WorkspacePicker()
            qtbot.addWidget(picker)

            assert not picker.recent_title.isVisible()
            assert not picker.recent_container.isVisible()

    def test_picker_shows_recent_dirs(self, qtbot):
        recent_paths = [Path("/home/user/project1"), Path("/home/user/project2")]

        with patch("omg_cli.gui.workspace_picker.get_config_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.list_recent_directories.return_value = recent_paths
            mock_get.return_value = mock_manager

            picker = WorkspacePicker()
            qtbot.addWidget(picker)

            assert picker.recent_title.isVisible()
            assert picker.recent_container.isVisible()

    def test_browse_button_opens_file_dialog(self, qtbot):
        with patch("omg_cli.gui.workspace_picker.get_config_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.list_recent_directories.return_value = []
            mock_manager.get_working_directory.return_value = None
            mock_get.return_value = mock_manager

            picker = WorkspacePicker()
            qtbot.addWidget(picker)

            with patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value="/selected/path"):
                with qtbot.waitSignal(picker.workspaceSelected, timeout=1000) as blocker:
                    picker.browse_button.click()

                assert blocker.args[0] == Path("/selected/path")

    def test_directory_selection_persists_and_emits(self, qtbot):
        selected_path = Path("/home/user/my-project")

        with patch("omg_cli.gui.workspace_picker.get_config_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.list_recent_directories.return_value = []
            mock_get.return_value = mock_manager

            picker = WorkspacePicker()
            qtbot.addWidget(picker)

            with qtbot.waitSignal(picker.workspaceSelected, timeout=1000) as blocker:
                picker._on_directory_selected(selected_path)

            assert blocker.args[0] == selected_path
            mock_manager.set_working_directory.assert_called_once_with(selected_path)
