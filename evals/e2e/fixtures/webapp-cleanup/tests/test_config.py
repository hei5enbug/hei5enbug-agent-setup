from webapp.config import Settings, load_dotenv, load_settings


def test_defaults():
    assert load_settings({}) == Settings()


def test_environment_overrides():
    settings = load_settings({"DEMO_PORT": "9000", "DEMO_DEBUG": "1", "DEMO_HOST": "0.0.0.0"})
    assert (settings.host, settings.port, settings.debug) == ("0.0.0.0", 9000, True)


def test_dotenv_skips_comments_and_blank_lines(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# comment\n\nA=1\nB = two\nbroken line\n", encoding="utf-8")
    assert load_dotenv(path) == {"A": "1", "B": "two"}


def test_missing_dotenv_gives_empty_mapping(tmp_path):
    assert load_dotenv(tmp_path / "nothing") == {}
