import json
import pytest
from pathlib import Path
from src.storage.manager import StorageManager, ConfigError, _expand_env_vars

def test_load_config_missing_file(tmp_path):
    storage = StorageManager(data_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        storage.load_config()

def test_load_config_invalid_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("invalid json", encoding="utf-8")
    
    storage = StorageManager(data_dir=str(tmp_path))
    with pytest.raises(ConfigError) as excinfo:
        storage.load_config()
    assert "Invalid JSON in configuration file" in str(excinfo.value)
    assert str(config_path) in str(excinfo.value)

def test_load_config_validation_failure(tmp_path):
    config_path = tmp_path / "config.json"
    # Missing required 'ai' and 'sources' fields
    config_path.write_text(json.dumps({"version": "1.0"}), encoding="utf-8")
    
    storage = StorageManager(data_dir=str(tmp_path))
    with pytest.raises(ConfigError) as excinfo:
        storage.load_config()
    assert "Configuration validation failed" in str(excinfo.value)
    assert str(config_path) in str(excinfo.value)

def test_load_config_success(tmp_path):
    config_path = tmp_path / "config.json"
    config_data = {
        "version": "1.0",
        "ai": {
            "provider": "anthropic",
            "model": "claude-3-sonnet",
            "api_key_env": "ANTHROPIC_API_KEY"
        },
        "sources": {
            "hackernews": {"enabled": True}
        },
        "filtering": {
            "ai_score_threshold": 7.0,
            "time_window_hours": 24
        }
    }
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    storage = StorageManager(data_dir=str(tmp_path))
    config = storage.load_config()
    assert config.version == "1.0"
    assert config.ai.provider == "anthropic"


class TestExpandEnvVars:
    """Recursive ${VAR} expansion on config dicts/lists/strings."""

    def test_expands_simple_reference(self, monkeypatch):
        monkeypatch.setenv("FOO", "bar")
        assert _expand_env_vars("prefix-${FOO}-suffix") == "prefix-bar-suffix"

    def test_expands_multiple_references_in_one_string(self, monkeypatch):
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        assert _expand_env_vars("${A}/${B}") == "1/2"

    def test_leaves_unset_var_as_placeholder(self, monkeypatch):
        monkeypatch.delenv("MISSING", raising=False)
        assert _expand_env_vars("${MISSING}") == "${MISSING}"

    def test_ignores_non_matching_patterns(self):
        assert _expand_env_vars("no braces here") == "no braces here"
        assert _expand_env_vars("$FOO without braces") == "$FOO without braces"
        assert _expand_env_vars("${123INVALID}") == "${123INVALID}"

    def test_recurses_into_dict(self, monkeypatch):
        monkeypatch.setenv("HOST", "api.example.com")
        result = _expand_env_vars({"url": "https://${HOST}/v1", "port": 443})
        assert result == {"url": "https://api.example.com/v1", "port": 443}

    def test_recurses_into_list(self, monkeypatch):
        monkeypatch.setenv("X", "hi")
        assert _expand_env_vars(["${X}", "plain", 7]) == ["hi", "plain", 7]

    def test_preserves_non_string_leaves(self):
        assert _expand_env_vars(42) == 42
        assert _expand_env_vars(3.14) == 3.14
        assert _expand_env_vars(True) is True
        assert _expand_env_vars(None) is None

    def test_deeply_nested(self, monkeypatch):
        monkeypatch.setenv("TOKEN", "secret")
        value = {
            "a": [
                {"b": "Bearer ${TOKEN}"},
                {"b": ["${TOKEN}", 1]},
            ],
        }
        out = _expand_env_vars(value)
        assert out["a"][0]["b"] == "Bearer secret"
        assert out["a"][1]["b"] == ["secret", 1]


def test_load_config_expands_env_vars_in_ai_base_url(tmp_path, monkeypatch):
    """Integration: proves base_url is env-expandable end-to-end.

    This is exactly the use case that keeps private/tenant endpoint
    URLs out of version control.
    """
    monkeypatch.setenv("HORIZON_AI_BASE_URL", "https://private-proxy.example/v1")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "version": "1.0",
        "ai": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "${HORIZON_AI_BASE_URL}",
        },
        "sources": {"hackernews": {"enabled": True}},
        "filtering": {"ai_score_threshold": 6.0, "time_window_hours": 24},
    }), encoding="utf-8")

    storage = StorageManager(data_dir=str(tmp_path))
    config = storage.load_config()
    assert config.ai.base_url == "https://private-proxy.example/v1"


class TestSubscribers:
    """Email subscriber list persistence (data/subscribers.json)."""

    def test_load_subscribers_returns_empty_list_when_file_missing(self, tmp_path):
        storage = StorageManager(data_dir=str(tmp_path))
        assert storage.load_subscribers() == []

    def test_load_subscribers_returns_empty_list_on_invalid_json(self, tmp_path):
        storage = StorageManager(data_dir=str(tmp_path))
        (tmp_path / "subscribers.json").write_text("not valid json", encoding="utf-8")
        assert storage.load_subscribers() == []

    def test_add_subscriber_creates_file_and_persists(self, tmp_path):
        storage = StorageManager(data_dir=str(tmp_path))
        storage.add_subscriber("alice@example.com")

        subscribers_path = tmp_path / "subscribers.json"
        assert subscribers_path.exists()
        assert storage.load_subscribers() == ["alice@example.com"]

    def test_add_subscriber_appends_to_existing_list(self, tmp_path):
        storage = StorageManager(data_dir=str(tmp_path))
        storage.add_subscriber("alice@example.com")
        storage.add_subscriber("bob@example.com")

        assert storage.load_subscribers() == ["alice@example.com", "bob@example.com"]

    def test_add_subscriber_is_idempotent(self, tmp_path):
        storage = StorageManager(data_dir=str(tmp_path))
        storage.add_subscriber("alice@example.com")
        storage.add_subscriber("alice@example.com")

        assert storage.load_subscribers() == ["alice@example.com"]

    def test_remove_subscriber_removes_existing(self, tmp_path):
        storage = StorageManager(data_dir=str(tmp_path))
        storage.add_subscriber("alice@example.com")
        storage.add_subscriber("bob@example.com")

        storage.remove_subscriber("alice@example.com")

        assert storage.load_subscribers() == ["bob@example.com"]

    def test_remove_subscriber_is_a_no_op_when_not_present(self, tmp_path):
        storage = StorageManager(data_dir=str(tmp_path))
        storage.add_subscriber("alice@example.com")

        storage.remove_subscriber("nobody@example.com")

        assert storage.load_subscribers() == ["alice@example.com"]

    def test_remove_subscriber_when_no_file_exists_does_not_raise(self, tmp_path):
        storage = StorageManager(data_dir=str(tmp_path))
        storage.remove_subscriber("alice@example.com")  # must not raise
        assert storage.load_subscribers() == []

    def test_subscribers_persist_across_manager_instances(self, tmp_path):
        StorageManager(data_dir=str(tmp_path)).add_subscriber("alice@example.com")

        # A fresh StorageManager pointed at the same data_dir (e.g. a
        # different process run) must see what the first instance wrote.
        reloaded = StorageManager(data_dir=str(tmp_path))
        assert reloaded.load_subscribers() == ["alice@example.com"]
