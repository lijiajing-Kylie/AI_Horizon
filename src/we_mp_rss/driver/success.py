"""Login status tracking (in-process globals — Redis stripped)."""
from __future__ import annotations

import json  # noqa: F401  (kept for parity with upstream)
import threading
import time
from typing import Optional

from .token import set_token
from ..core.print import print_warning, print_success

# 全局变量（作为Redis不可用时的回退）
WX_LOGIN_ED = False
WX_LOGIN_INFO = None

login_lock = threading.Lock()

REDIS_KEY_STATUS = "werss:login:status"  # kept for reference; Redis unused


def setStatus(status: bool) -> None:
    """Set login status (in-process global)."""
    global WX_LOGIN_ED
    with login_lock:
        WX_LOGIN_ED = status


def getStatus() -> bool:
    """Get login status, checking whether the token is still valid."""
    global WX_LOGIN_ED
    with login_lock:
        in_mem = WX_LOGIN_ED

    token_data = getLoginInfo()
    has_token = bool(token_data and token_data.get("token"))

    # 跨进程兼容：内存标记只在同一进程内有效（login 进程）。新进程（status /
    # 抓取）必须回退到持久化的 wx.lic 判断 —— token 文件里存在未过期的 token
    # 即视为已登录。
    if not in_mem and not has_token:
        return False

    if token_data and "expiry" in token_data and token_data["expiry"]:
        expiry = token_data["expiry"]
        if "remaining_seconds" in expiry:
            remaining = expiry["remaining_seconds"]
            if remaining is not None and remaining > 0:
                return True
            else:
                print_warning("Token已过期，需要重新登录")
                setStatus(False)
                return False
        elif "expiry_timestamp" in expiry:
            expiry_timestamp = expiry["expiry_timestamp"]
            if expiry_timestamp and expiry_timestamp >= time.time():
                return True
            else:
                print_warning("Token已过期，需要重新登录")
                setStatus(False)
                return False
    return True


def getLoginInfo() -> Optional[dict]:
    from .token import _get_token_data
    return _get_token_data()


def Success_Msg(data: dict, ext_data: dict = {}) -> None:
    from ..core.config import cfg
    text = "# 授权成功\n"
    text += f"- 服务名：{cfg.get('server.name', '')}\n"
    text += f"- 名称：{ext_data['wx_app_name']}\n"
    text += f"- Token: {data['token']}\n"
    text += f"- 有效时间: {data['expiry']['expiry_time']}\n"
    print_success(text)


def Success(data: dict, ext_data: dict = {}) -> None:
    if data is not None:
        if ext_data is not {}:
            print_success(f"名称：{ext_data['wx_app_name']}")
        if data["expiry"] is not None:
            Success_Msg(data, ext_data)
            print_success(
                f"有效时间: {data['expiry']['expiry_time']} "
                f"(剩余秒数: {data['expiry']['remaining_seconds']}) Token: {data['token']}"
            )
            set_token(data, ext_data)
            setStatus(True)
        else:
            print_warning("登录失败，请检查上述错误信息")
            setStatus(False)
    else:
        print("\n登录失败，请检查上述错误信息")
        setStatus(False)


def CanGetToken() -> bool:
    """Check whether a usable token exists (login status + expiry)."""
    if not getStatus():
        print_warning("当前未登录，请先扫码登录")
        return False

    token_data = getLoginInfo()
    if not token_data or not token_data.get("token"):
        print_warning("Token不存在，请重新登录")
        setStatus(False)
        return False

    expiry = token_data.get("expiry")
    if expiry:
        if "remaining_seconds" in expiry:
            remaining = expiry["remaining_seconds"]
            if remaining is not None and remaining <= 0:
                print_warning("Token已过期，请重新扫码登录")
                setStatus(False)
                return False
        elif "expiry_timestamp" in expiry:
            expiry_timestamp = expiry["expiry_timestamp"]
            if expiry_timestamp and expiry_timestamp <= time.time():
                print_warning("Token已过期，请重新扫码登录")
                setStatus(False)
                return False

    return True
