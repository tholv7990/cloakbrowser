import os
from unittest.mock import MagicMock, patch

from cloakbrowser import launch


@patch("cloakbrowser.browser.ensure_binary")
@patch("playwright.sync_api.sync_playwright")
def test_extension_loading(mock_sync_playwright, mock_ensure_binary):
    mock_ensure_binary.return_value = "/fake/chrome"

    mock_browser = MagicMock()

    mock_pw = MagicMock()
    mock_pw.chromium.launch.return_value = mock_browser

    mock_sync_playwright.return_value.start.return_value = mock_pw

    extension_paths = ["./extension one", "./extension;two"]
    launch(extension_paths=extension_paths)

    mock_pw.chromium.launch.assert_called_once()

    launch_call = mock_pw.chromium.launch.call_args

    args = launch_call.kwargs["args"]

    absolute_paths = [os.path.abspath(path) for path in extension_paths]
    load_flags = [arg for arg in args if arg.startswith("--load-extension=")]
    allow_flags = [
        arg for arg in args if arg.startswith("--disable-extensions-except=")
    ]

    assert len(load_flags) == len(allow_flags) == 1
    assert load_flags[0].split("=", 1)[1].split(",") == absolute_paths
    assert allow_flags[0].split("=", 1)[1].split(",") == absolute_paths
