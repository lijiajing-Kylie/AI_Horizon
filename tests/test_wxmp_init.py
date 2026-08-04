"""we_mp_rss.init() 幂等 + import 无副作用测试。

注意：这些测试绝不触碰真实的 ``data/`` 目录（那里存放微信登录态），
一律在 pytest 提供的临时目录中验证。
"""

from __future__ import annotations

import os


class _FakeWxmpConfig:
    gather_content = True
    clean_html = False
    proxy = None
    max_page = 1
    gather_interval = 3
    data_dir = "data/wxmp"


def test_import_has_no_side_effect(monkeypatch, tmp_path) -> None:
    """Importing the bundled package must not create data files or hit the network.

    Runs inside a temp cwd so the real ``data/`` (with any login state) is
    never touched or deleted.
    """
    monkeypatch.chdir(tmp_path)

    # Reset the global cfg to its initial (empty) dict-injection state.
    from src.we_mp_rss.core.config import cfg

    cfg.config = {}
    cfg._config = {}

    import src.we_mp_rss  # noqa: F401
    import src.we_mp_rss.core.config  # noqa: F401
    import src.we_mp_rss.core.wx.base  # noqa: F401
    import src.we_mp_rss.driver.token  # noqa: F401
    import src.we_mp_rss.driver.store  # noqa: F401
    import src.we_mp_rss.driver.success  # noqa: F401
    import src.we_mp_rss.driver.wx_api  # noqa: F401
    import src.we_mp_rss.driver.wxarticle  # noqa: F401

    # cfg must start empty (dict-injection mode), no config.yaml read.
    assert cfg.get("gather.model", None) is None

    # Import alone must not create the data/wxmp directory (in the temp cwd).
    assert not os.path.isdir("data/wxmp")


def test_init_config_survives_reload(tmp_path) -> None:
    """Regression: ``cfg.reload()`` must not wipe the dict-injected config.

    The scraping flow calls ``cfg.reload()`` inside ``WxGather.get_token()``.
    With an empty ``config_path`` (dict-injection mode) the old code reset the
    config to ``{}``, so ``gather.content`` fell back to its default ``False``
    and we-mp-rss never fetched article bodies.
    """
    import src.we_mp_rss
    from src.we_mp_rss.core.config import cfg

    src.we_mp_rss.init(_FakeWxmpConfig(), str(tmp_path))
    assert cfg.get("gather.content") is True

    # Exactly what WxGather.get_token() does — must not clear seeded values.
    cfg.reload()

    assert cfg.get("gather.content") is True
    assert cfg.get("gather.model") == "web"
    assert cfg.get("gather.clean_html") is False


def test_init_creates_data_dir_and_is_idempotent(tmp_path) -> None:
    import src.we_mp_rss

    src.we_mp_rss.init(_FakeWxmpConfig(), str(tmp_path))
    assert os.path.isdir(str(tmp_path))

    # Second call must not raise (idempotent).
    src.we_mp_rss.init(_FakeWxmpConfig(), str(tmp_path))

    # Config seeded from the fake config.
    assert src.we_mp_rss.cfg.get("gather.model") == "web"
    assert src.we_mp_rss.cfg.get("gather.content") is True
    assert src.we_mp_rss.cfg.get("server.auth_web") is False


def test_init_points_token_store_at_data_dir(tmp_path) -> None:
    import src.we_mp_rss
    from src.we_mp_rss.driver import token

    src.we_mp_rss.init(_FakeWxmpConfig(), str(tmp_path))

    token.set_token(
        {
            "token": "tok123",
            "cookies_str": "c=1",
            "fingerprint": "fp",
            "expiry": {"expiry_time": "2026-08-01", "remaining_seconds": 3600},
        }
    )
    lic = os.path.join(str(tmp_path), "wx.lic")
    assert os.path.exists(lic)
    assert token.get("token") == "tok123"
