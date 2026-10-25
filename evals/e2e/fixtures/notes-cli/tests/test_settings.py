import pytest

from notes_cli.settings import DEFAULT_SETTINGS_PATH, SettingsError, load_settings


def test_shipped_settings_hold_a_positive_page_size():
    assert load_settings(DEFAULT_SETTINGS_PATH).page_size >= 1


def test_page_size_is_read_from_the_file(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("page_size = 7\n", encoding="utf-8")
    assert load_settings(path).page_size == 7


@pytest.mark.parametrize("text", ["page_size = 0\n", 'page_size = "ten"\n', "other = 1\n", "page_size ="])
def test_unusable_settings_are_rejected(tmp_path, text):
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(path)


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(SettingsError):
        load_settings(tmp_path / "missing.toml")
