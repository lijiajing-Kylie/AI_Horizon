#!/Users/kylie/Horizon/.venv/bin/python3
"""微信读书登录态巡检 cron 入口(核心逻辑见 src/services/auth_alert.py)。

逻辑:调用 ``horizon-wxmp status`` 真实探测 token(见 ``src/wxmp_cli.py``),
rc!=0 表示登录失效/未登录,按 24h cooldown 去重后向通用 webhook
(``HORIZON_WEBHOOK_URL``,回退 ``DINGTALK_WEBHOOK_URL``)发告警。
日志与告警状态:data/logs/weread-auth-check.log / weread-alert-state.json。

crontab(本机时区,每天三次):
    0 10 * * * /Users/kylie/Horizon/scripts/check_weread_login.py
    0 14 * * * /Users/kylie/Horizon/scripts/check_weread_login.py
    0 17 * * * /Users/kylie/Horizon/scripts/check_weread_login.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.auth_alert import main  # noqa: E402 — 需先补 sys.path

if __name__ == "__main__":
    sys.exit(main())
