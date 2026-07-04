import os

from meetily_detector import config as configmod


def test_defaults_from_empty_dict():
    cfg = configmod.from_dict({})
    assert cfg.enabled is True
    assert cfg.poll_interval_seconds == 5
    assert cfg.detection.mic_debounce_polls == 2
    assert cfg.detection.stop_idle_polls == 6
    # default google-meet rule is present and enabled
    rules = cfg.enabled_rules()
    assert any(r.name == "google-meet" for r in rules)


def test_notion_token_env_override(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "secret_from_env")
    cfg = configmod.from_dict({"notion": {"token": "in_file"}})
    assert cfg.notion.token == "secret_from_env"


def test_platform_rules_parsed():
    raw = {
        "platforms": {
            "rule": [
                {"name": "google-meet", "enabled": True, "url_regex": "^https://meet"},
                {"name": "zoom-web", "enabled": False, "url_regex": "^https://zoom"},
            ]
        }
    }
    cfg = configmod.from_dict(raw)
    names = {r.name for r in cfg.enabled_rules()}
    assert names == {"google-meet"}  # zoom disabled


def test_load_missing_file_returns_defaults(tmp_path):
    cfg = configmod.load(str(tmp_path / "nope.toml"))
    assert cfg.enabled is True
    assert cfg.enabled_rules()


def test_snooze_roundtrip(tmp_path):
    path = str(tmp_path / "snooze.json")
    assert configmod.is_snoozed(1000.0, path) is False
    configmod.snooze_until(hours=2, now=1000.0, path=path)
    assert configmod.is_snoozed(1000.0, path) is True
    assert configmod.is_snoozed(1000.0 + 3 * 3600, path) is False  # expired
    configmod.clear_snooze(path)
    assert not os.path.exists(path)
    assert configmod.is_snoozed(1000.0, path) is False
