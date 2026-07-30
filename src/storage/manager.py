"""Storage manager for configuration and state persistence."""

import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..models import Config


# Matches ${VAR_NAME} in string config values. Names follow env-var rules
# (ASCII letters, digits, underscore; must not start with a digit).
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ``${VAR}`` references inside any string leaves.

    Containers (dicts, lists, tuples) are walked; non-string leaves are
    returned unchanged. Strings with no ``${...}`` tokens are returned
    unchanged. References to unset variables are **left as-is**, so
    ``${MISSING}`` round-trips to ``${MISSING}`` and surfaces as a clear
    downstream error rather than a silent empty string.

    This is intentionally identical to the behaviour ``RSSScraper`` uses
    for RSS feed URLs, so a single ``${VAR}`` convention works everywhere
    in the config (AI ``base_url``, feed URLs, webhook URLs, ...).
    """
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(
            lambda m: os.environ.get(m.group(1), m.group(0)),
            value,
        )
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_expand_env_vars(v) for v in value)
    return value


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""

    pass


class StorageManager:
    """Manages file-based storage for configuration and state."""

    # 多文件合并顺序 — 越后面的文件优先级越高
    _MERGE_FILES = ["app.json", "sources.json", "scoring.json"]

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.config_path = self.data_dir / "config.json"
        self.summaries_dir = self.data_dir / "summaries"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.summaries_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _deep_merge(base: dict, overlay: dict) -> dict:
        """递归合并两个 dict。dict 值递归合并，list/其他值直接替换。"""
        result = dict(base)
        for key, val in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = StorageManager._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    def load_config(self) -> Config:
        # 1. 尝试 Python 配置文件（data/config.py），支持注释和动态值
        py_config = self.data_dir / "config.py"
        if py_config.exists():
            return self._load_config_py(py_config)

        # 2. JSON 多文件合并（备选）
        return self._load_config_json()

    def _load_config_py(self, path: Path) -> Config:
        """加载 Python 配置文件并执行，提取 dict 变量作为配置数据。"""
        # 用唯一模块名加载，避免 sys.modules 缓存干扰
        module_name = f"_horizon_config_{hash(path)}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ConfigError(f"Could not load Python config: {path}")
        mod = importlib.util.module_from_spec(spec)
        # 注入 os 模块，方便用户在 config.py 中用 os.getenv()
        mod.os = os
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:
            raise ConfigError(f"Error executing {path}: {exc}") from exc
        finally:
            sys.modules.pop(module_name, None)

        # 提取模块中公开的 dict/list 变量作为配置
        merged: dict = {}
        for key in dir(mod):
            if key.startswith("_"):
                continue
            val = getattr(mod, key, None)
            if isinstance(val, (dict, list, str, int, float, bool)):
                # list 类型的变量（如 sources.rss）需要包在对应的父 key 下
                # 顶层变量直接作为 Config 模型的字段
                if val is not None:
                    merged[key] = val

        if not merged:
            raise ConfigError(
                f"Python config {path} defines no configuration variables. "
                "Define dicts like `ai = {...}`, `sources = {...}`, etc."
            )

        # 展开 ${VAR} 引用
        merged = _expand_env_vars(merged)

        try:
            return Config.model_validate(merged)
        except ValidationError as e:
            raise ConfigError(
                f"Configuration validation failed (source: {path})\n"
                f"Details: {e}"
            ) from e

    def _load_config_json(self) -> Config:
        # 1. 多文件合并：app.json + sources.json + scoring.json
        merged: dict = {}
        for name in self._MERGE_FILES:
            path = self.data_dir / name
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        merged = self._deep_merge(merged, json.load(f))
                except json.JSONDecodeError as e:
                    raise ConfigError(f"Invalid JSON in {path}: {e}") from e

        # 2. config.json 作为覆盖层（向后兼容，优先级最高）
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    merged = self._deep_merge(merged, json.load(f))
            except json.JSONDecodeError as e:
                raise ConfigError(
                    f"Invalid JSON in configuration file: {self.config_path}\n"
                    f"Error: {e}"
                ) from e
            _source = str(self.config_path)
        elif merged:
            _source = "+".join(str(self.data_dir / n) for n in self._MERGE_FILES if (self.data_dir / n).exists())
        else:
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}\n"
                f"Alternatively, place individual config files in {self.data_dir}/\n"
                f"({', '.join(self._MERGE_FILES)}) based on config.example.json."
            )

        # 3. 展开 ${VAR} 引用
        merged = _expand_env_vars(merged)

        # 4. Pydantic 验证
        try:
            return Config.model_validate(merged)
        except ValidationError as e:
            raise ConfigError(
                f"Configuration validation failed (source: {_source})\n"
                f"Details: {e}"
            ) from e

    def save_config(self, config: Config, backup: bool = True) -> Path:
        """Save configuration to config.json, optionally backing up the existing file.

        Args:
            config: The Config object to save.
            backup: If True and config.json exists, copy it to config.json.bak first.

        Returns:
            Path to the saved config file.
        """
        if backup and self.config_path.exists():
            shutil.copy2(self.config_path, self.config_path.with_suffix(".json.bak"))

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config.model_dump(mode="json"), f, indent=2, ensure_ascii=False)
            f.write("\n")

        return self.config_path

    def save_daily_summary(self, date: str, markdown: str, language: str = "en") -> Path:
        filename = f"horizon-{date}-{language}.md"
        filepath = self.summaries_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown)

        return filepath

    def publish_to_github_pages(self, date: str, markdown: str, language: str = "en") -> Path:
        """Copy a daily summary into ``docs/_posts/`` as a Jekyll post.

        Adds Jekyll front matter and strips the leading H1 header (Jekyll
        renders its own title from front matter, so a duplicate H1 would
        show up twice on the page).
        """
        posts_dir = Path("docs/_posts")
        posts_dir.mkdir(parents=True, exist_ok=True)

        post_filename = f"{date}-summary-{language}.md"
        dest_path = posts_dir / post_filename

        front_matter = (
            "---\n"
            "layout: default\n"
            f"title: \"Horizon Summary: {date} ({language.upper()})\"\n"
            f"date: {date}\n"
            f"lang: {language}\n"
            "---\n\n"
        )

        summary_content = markdown
        first_line = summary_content.strip().split("\n")[0]
        if first_line.startswith("# "):
            parts = summary_content.split("\n", 1)
            if len(parts) > 1:
                summary_content = parts[1].strip()

        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(front_matter + summary_content)

        return dest_path

    def load_subscribers(self) -> list:
        """Loads the list of email subscribers."""
        subscribers_path = self.data_dir / "subscribers.json"
        if not subscribers_path.exists():
            return []

        try:
            with open(subscribers_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []

    def add_subscriber(self, email_addr: str):
        """Adds a new subscriber email."""
        subscribers = self.load_subscribers()
        if email_addr not in subscribers:
            subscribers.append(email_addr)
            self._save_subscribers(subscribers)

    def remove_subscriber(self, email_addr: str):
        """Removes a subscriber email."""
        subscribers = self.load_subscribers()
        if email_addr in subscribers:
            subscribers.remove(email_addr)
            self._save_subscribers(subscribers)

    def _save_subscribers(self, subscribers: list):
        """Helper to save subscribers list."""
        subscribers_path = self.data_dir / "subscribers.json"
        with open(subscribers_path, "w", encoding="utf-8") as f:
            json.dump(subscribers, f, indent=2)
