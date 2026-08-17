"""Tests for horizon-wxmp subscribe / migrate CLI commands.

CONFIG_PATH is redirected to a temp file so no real data/config.py is touched.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src import wxmp_cli
from src.models import WxMpConfig, WxMpSourceConfig
from src.we_read.model import WeReadMpInfo

CONFIG_TMPL = (
    'sources = {\n'
    '    "wxmp": {\n'
    '        "enabled": False,\n'
    '        "feeds": [\n'
    '        ],\n'
    '    },\n'
    '}\n'
)


def _fake_wxmp(tmp_path) -> WxMpConfig:
    return WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )


class _FakeStore:
    def __init__(self, present: bool = True) -> None:
        self.present = present

    def is_present(self) -> bool:
        return self.present


class _FakeClient:
    def __init__(self, by_link: dict | None = None, store_present: bool = True) -> None:
        self.by_link = by_link or {}
        self.store = _FakeStore(store_present)

    async def resolve_share(self, link: str):
        return self.by_link.get(link, [])


def _write_cfg(tmp_path) -> Path:
    p = tmp_path / "config.py"
    p.write_text(CONFIG_TMPL, encoding="utf-8")
    return p


def _patch_env(monkeypatch, tmp_path, client: _FakeClient, wxmp: WxMpConfig) -> None:
    monkeypatch.setattr(wxmp_cli, "CONFIG_PATH", _write_cfg(tmp_path))
    monkeypatch.setattr(wxmp_cli, "_load_wxmp_config", lambda: wxmp)
    monkeypatch.setattr(
        wxmp_cli,
        "build_client_from_wxmp_config",
        lambda cfg, http_client=None: client,
    )


def test_subscribe_dry_run_does_not_write(monkeypatch, tmp_path) -> None:
    client = _FakeClient(
        by_link={"https://mp.weixin.qq.com/s/abc": [WeReadMpInfo(id="MP_WXS_1", name="新智元")]}
    )
    _patch_env(monkeypatch, tmp_path, client, _fake_wxmp(tmp_path))
    args = argparse.Namespace(
        link="https://mp.weixin.qq.com/s/abc", name=None, category=None,
        write=False, enable=False,
    )
    assert wxmp_cli._cmd_subscribe(args) == 0
    assert "MP_WXS_1" not in wxmp_cli.CONFIG_PATH.read_text(encoding="utf-8")


def test_subscribe_write(monkeypatch, tmp_path) -> None:
    client = _FakeClient(
        by_link={"https://mp.weixin.qq.com/s/abc": [WeReadMpInfo(id="MP_WXS_1", name="新智元")]}
    )
    _patch_env(monkeypatch, tmp_path, client, _fake_wxmp(tmp_path))
    args = argparse.Namespace(
        link="https://mp.weixin.qq.com/s/abc", name=None, category=None,
        write=True, enable=True,
    )
    assert wxmp_cli._cmd_subscribe(args) == 0
    text = wxmp_cli.CONFIG_PATH.read_text(encoding="utf-8")
    assert "MP_WXS_1" in text
    assert '"enabled": True' in text


def test_subscribe_requires_login(monkeypatch, tmp_path) -> None:
    client = _FakeClient(store_present=False)
    _patch_env(monkeypatch, tmp_path, client, _fake_wxmp(tmp_path))
    args = argparse.Namespace(
        link="https://mp.weixin.qq.com/s/abc", name=None, category=None,
        write=False, enable=False,
    )
    assert wxmp_cli._cmd_subscribe(args) == 1


def test_migrate_write(monkeypatch, tmp_path) -> None:
    client = _FakeClient(
        by_link={
            "https://mp.weixin.qq.com/s/a": [WeReadMpInfo(id="MP_WXS_A", name="甲")],
            "https://mp.weixin.qq.com/s/b": [WeReadMpInfo(id="MP_WXS_B", name="乙")],
            "https://mp.weixin.qq.com/s/c": [],  # 未收录
        }
    )
    _patch_env(monkeypatch, tmp_path, client, _fake_wxmp(tmp_path))
    links_file = tmp_path / "links.txt"
    links_file.write_text(
        "https://mp.weixin.qq.com/s/a\n"
        "https://mp.weixin.qq.com/s/b\n"
        "https://mp.weixin.qq.com/s/c\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(links_file=str(links_file), write=True, yes=True, enable=True)
    assert wxmp_cli._cmd_migrate(args) == 0
    text = wxmp_cli.CONFIG_PATH.read_text(encoding="utf-8")
    assert "MP_WXS_A" in text
    assert "MP_WXS_B" in text
    assert '"enabled": True' in text


def test_migrate_dry_run_writes_nothing(monkeypatch, tmp_path) -> None:
    client = _FakeClient(
        by_link={"https://mp.weixin.qq.com/s/a": [WeReadMpInfo(id="MP_WXS_A", name="甲")]}
    )
    _patch_env(monkeypatch, tmp_path, client, _fake_wxmp(tmp_path))
    links_file = tmp_path / "links.txt"
    links_file.write_text("https://mp.weixin.qq.com/s/a\n", encoding="utf-8")
    args = argparse.Namespace(links_file=str(links_file), write=False, yes=False, enable=False)
    rc = wxmp_cli._cmd_migrate(args)
    assert rc == 0
    assert "MP_WXS_A" not in wxmp_cli.CONFIG_PATH.read_text(encoding="utf-8")


def test_migrate_missing_file_returns_error(tmp_path) -> None:
    args = argparse.Namespace(links_file=str(tmp_path / "nope.txt"))
    assert wxmp_cli._cmd_migrate(args) == 1
