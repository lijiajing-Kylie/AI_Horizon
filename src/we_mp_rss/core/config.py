"""Configuration (trimmed from we-mp-rss ``core/config.py``).

The bundled core is configured by *dict injection*: call
``we_mp_rss.init(wxmp_config, data_dir)`` to seed the module-level ``cfg``
singleton from a Horizon ``WxMpConfig`` — no config.yaml on disk.  The
``Config`` class keeps the original dotted-key ``.get()`` / ``${VAR}``
behaviour so upstream code paths work unchanged.
"""
from __future__ import annotations

import argparse
import os
from typing import Any, Optional

import yaml

from .file import FileCrypto
from .print import print_warning, print_error


class Config:
    config_path = ""
    config: dict = {}
    _config_cache = None

    def __init__(
        self,
        config_path: Optional[str] = None,
        encrypt: bool = False,
        initial_data: Optional[dict] = None,
    ):
        self.args = None
        self.config_path = config_path or ""
        self.encryption_enabled = encrypt

        if initial_data is not None:
            # Dict-injection mode — skip file I/O entirely.
            self.config = initial_data
            self._config = self.replace_env_vars(initial_data)
            return

        self.args = self.parse_args()
        self.config_path = config_path or self.args.config
        if os.path.dirname(self.config_path) != "":
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        self.get_config()
        self._init_encryption()

    def _init_encryption(self) -> None:
        """Initialise optional encryption."""
        key = os.getenv("ENCRYPTION_KEY", "store.csol.store.werss")
        if self.encryption_enabled:
            try:
                self.crypto = FileCrypto(key)
            except Exception as e:
                print(f"加密初始化失败: {e}")
                self.encryption_enabled = False

    def parse_args(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser()
        parser.add_argument("-config", help="配置文件", default="config.yaml")
        parser.add_argument("-job", help="启动任务", default=False)
        parser.add_argument("-init", help="初始化数据库,初始化用户", default=False)
        args, _ = parser.parse_known_args()
        return args

    def _encrypt(self, data):
        if not self.encryption_enabled or not hasattr(self, "crypto"):
            return data
        try:
            if isinstance(data, str):
                return self.crypto.encrypt(data.encode("utf-8")).decode("utf-8")
            return self.crypto.encrypt(data).decode("utf-8")
        except Exception as e:
            print(f"加密失败: {e}")
            return data

    def _decrypt(self, data):
        if not self.encryption_enabled or not hasattr(self, "crypto"):
            return data
        try:
            if isinstance(data, str):
                return self.crypto.decrypt(data.encode("utf-8")).decode("utf-8")
            return self.crypto.decrypt(data).decode("utf-8")
        except Exception as e:
            print(f"解密失败: {e}")
            return data

    def save_config(self) -> None:
        config_to_save = self.config.copy()
        try:
            yaml_content = yaml.dump(config_to_save)
            try:
                yaml.safe_load(yaml_content)
            except yaml.YAMLError as ye:
                print_error(f"YAML格式验证失败: {ye}")
                raise
            encrypted_content = self._encrypt(yaml_content)
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(encrypted_content)
            self.reload()
        except Exception as e:
            print_error(f"保存配置文件失败: {e}")
            raise

    def replace_env_vars(self, data):
        if isinstance(data, dict):
            return {k: self.replace_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.replace_env_vars(item) for item in data]
        elif isinstance(data, str):
            try:
                import re
                pattern = re.compile(r"\$\{([^}:]+)(?::-([^}]*))\}")
                def replace_match(match):
                    var_name = match.group(1)
                    default_value = match.group(2)
                    return (
                        os.getenv(var_name, default_value)
                        if default_value is not None
                        else os.getenv(var_name, "")
                    )
                return pattern.sub(replace_match, data)
            except Exception:
                return data
        return data

    def get_config(self) -> dict:
        if not self.config_path:
            # Dict-injection mode (no config file on disk).
            self.config = {}
            self._config = {}
            return self.config
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                content = f.read()
                if self.encryption_enabled:
                    try:
                        decrypted_content = self._decrypt(content)
                        config = yaml.safe_load(decrypted_content)
                    except Exception as e:
                        print(f"解密配置文件失败: {e}")
                        config = {}
                else:
                    config = yaml.safe_load(content)
                if config is None:
                    config = {}
                self.config = config
                self._config = self.replace_env_vars(config)
                return self.config
        except Exception as e:
            print_error(f"加载配置文件 {self.config_path} 错误: {e}")
            return {}

    def reload(self) -> dict:
        if not self.config_path:
            # Dict-injection mode: config was seeded via ``we_mp_rss.init()``
            # and there is no config.yaml on disk to reload from.  Reloading
            # would reset the config to ``{}`` and silently revert e.g.
            # ``gather.content`` to its default ``False`` — so keep the
            # in-memory config as-is.
            return self.config
        self.config = self.get_config()
        return self.config

    def set(self, key, default: Any = None) -> None:
        self.config[key] = default
        self.save_config()

    def __fix(self, v: str):
        if v in ("", "''", '""', None):
            return ""
        try:
            if v.lower() in ("true", "false"):
                return v.lower() == "true"
            if v.isdigit():
                return int(v)
            if "." in v and all(part.isdigit() for part in v.split(".") if part):
                return float(v)
            return v
        except Exception:
            return v

    def get(self, key, default: Any = None):
        _config = self.replace_env_vars(self.config)
        keys = key.split(".") if isinstance(key, str) else [key]
        value = _config
        try:
            for k in keys:
                value = value[k]
            val = self.__fix(value)
            if val is None and default is not None:
                return default
            return val
        except (KeyError, TypeError):
            pass
        return default


# ── module-level singleton (empty by default; seeded via we_mp_rss.init()) ──
cfg = Config(initial_data={})


def set_config(key: str, value: str) -> None:
    cfg.set(key, value)


def save_config() -> None:
    cfg.save_config()


def build_config_dict(wxmp_config: Any) -> dict:
    """Map a Horizon ``WxMpConfig`` into the bundled core's config dict.

    Only keys the bundled scraping code reads are produced.
    """
    proxy = getattr(wxmp_config, "proxy", None) or None
    lic_key = getattr(wxmp_config, "lic_key", None) or os.getenv(
        "WXMP_LIC_KEY", "RACHELOS"
    )
    return {
        "gather": {
            "model": "web",
            "content": bool(getattr(wxmp_config, "gather_content", True)),
            "clean_html": bool(getattr(wxmp_config, "clean_html", False)),
            "browser_type": "chromium",
            "max_page": int(getattr(wxmp_config, "max_page", 1)),
            "interval": int(getattr(wxmp_config, "gather_interval", 3)),
        },
        "proxy": {
            "enabled": bool(proxy),
            "hits": proxy or "",
            # base.py:_get_proxies 读取 proxy.http_url；WxMpConfig.proxy 是单个
            # HTTP 代理字符串，这里同时映射到 http_url 使其真正生效。
            "http_url": proxy or "",
        },
        "safe": {"lic_key": lic_key},
        "server": {
            "auth_web": False,
            "name": "Horizon",
        },
        "log": {"level": "INFO", "file": ""},
    }
