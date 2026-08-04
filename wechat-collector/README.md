# wechat-collector（独立微信公众号 collector）

一个**纯增量**的最小 debug 工具：直接驱动 `src/we_mp_rss`（内置 we-mp-rss v1.5.2 核心），
**不加载 Horizon 的任何配置 / 模型 / 管道**，也不改动现有代码。用于单独调试微信抓取链路。

## 文件

| 文件 | 作用 |
|---|---|
| `collector.py` | 独立 driver：`login` / `status` / `fetch` 子命令，含可复用函数 `fetch_recent` |
| `test_fetch_recent.py` | 最小测试脚本：验证能否获取指定公众号最近 5 篇文章 |
| `accounts.json` | 公众号名称 → feed_id 映射（与 `data/config.py` 的 `sources.wxmp.feeds` 一致） |
| `README.md` | 本说明 |

## 命令

所有命令从**仓库根目录**运行（`uv run` 提供项目依赖环境）：

```bash
# 1) 查看登录状态（首次运行预期为"未登录"）
uv run python wechat-collector/collector.py status

# 2) 首次使用：扫码登录（会弹出/打印二维码，写入 data/wxmp/wx.lic + key.lic）
uv run python wechat-collector/collector.py login

# 3) 最小测试：获取某公众号最近 5 篇文章（不发浏览器）
uv run python wechat-collector/test_fetch_recent.py 机器之心
uv run python wechat-collector/test_fetch_recent.py --feed-id MP_WXS_3073282833

# 4) 列出内置公众号
uv run python wechat-collector/test_fetch_recent.py --list
uv run python wechat-collector/collector.py fetch --list

# 5) 用 collector 直接抓取（默认 5 篇，不发浏览器；--content 才抓正文）
uv run python wechat-collector/collector.py fetch 机器之心
uv run python wechat-collector/collector.py fetch --feed-id MP_WXS_3073282833 --limit 3
```

## login 首次使用流程

1. `uv run python wechat-collector/collector.py status` —— 确认未登录（`data/wxmp/wx.lic`
   当前无有效 token）。
2. `uv run python wechat-collector/collector.py login` —— 生成二维码并保存到
   `data/wxmp/wx_qrcode.png`，macOS 下会自动 `open` 打开图片；用微信「扫一扫」确认登录，
   成功后写入 `data/wxmp/wx.lic` + `key.lic`。
3. 再次 `status` 应显示"已登录"。

> 提示：若 `login` 提示"登录脚本正在运行"，删除 `data/wxmp/wx_qrcode.png` 后重试。
> 若纯 requests 扫码受限未能取到 token，可改用 Horizon 自带的 `uv run horizon-wxmp login`
> （或 Playwright 方式）登录——两者共享同一份 `data/wxmp` 登录态文件。

## 常见问题：微信端频率限制

`fetch` / 测试脚本复用与主管道**完全相同**的调用链（`MpsWeb.get_Articles`），因此微信接口
返回频率限制（`ret=200013`）时的行为也一致：内置代码会按 60/120/180 秒指数退避自动重试，
单次抓取可能因此耗时 3 分多钟，最终仍取不到文章时脚本如实报告 `FAIL` 并返回 exit 1。

这属于**外部端点条件**（当前微信会话/IP 被限流），不是本工具的问题：

- `collector.py status` 显示"已登录"说明 token 本身有效，可稍后重试。
- 连续对多个公众号发起请求更容易触发限流，建议两次抓取之间间隔几分钟。
- 限流时重试逻辑是 vendored 核心内置的，本目录不修改任何现有代码，故保持原样。

## 与 Horizon 现有集成的边界

- 本目录**不修改、不删除任何现有文件**，也不触碰 `pyproject.toml`；所需依赖
  （requests / PyYAML / pillow / colorama / bs4）已在 Horizon 基础依赖中。
- collector **只 import `src.we_mp_rss` 核心 + 标准库**，不 import `src.models` /
  `src.storage` / `src.orchestrator` / `src.scrapers.wxmp`。
- `data_dir` 默认 `data/wxmp`，**复用 Horizon 的登录态文件**：本工具登录的 token
  对主管道同样有效，反之亦然。
- collector 仅用于独立调试，**不改变 Horizon 的任何运行行为**；主管道的微信抓取仍走
  `src/scrapers/wxmp.py`（`horizon-wxmp login` 管理登录态）。
