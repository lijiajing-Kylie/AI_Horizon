"""QR login flow for the WeRead channel.

The forwarding service returns ``scan_url`` (an open.weixin.qq.com confirm
link) rather than a QR image, so we render it locally with ``segno`` (a small
pure-Python dependency, already proven in the spike). Rendering is pluggable
via callbacks so the CLI can render terminal ASCII and/or open the PNG.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from .client import WeReadClient
from .model import WeReadLoginSession

# Callback types: called with the rendered PNG path / a message.
QrCallback = Callable[[Path], None]
PrintCallback = Callable[[str], None]


def render_qr_png(scan_url: str, path: Path) -> bool:
    """Render ``scan_url`` into a QR PNG at ``path``. Returns success."""
    try:
        import segno

        qr = segno.make(scan_url, error="m")
        qr.save(str(path), scale=6, border=2)
        return True
    except Exception:  # noqa: BLE001 - best-effort rendering
        return False


def render_terminal_ascii(path: Path, print_fn: PrintCallback = print) -> None:
    """Best-effort terminal ASCII QR from a PNG."""
    try:
        from PIL import Image

        img = Image.open(path).convert("L")
        w, h = img.size
        target_w = 40
        new_w = min(w, target_w)
        new_h = max(1, int(h * (new_w / w)))
        img = img.resize((new_w, new_h))
        px = img.load()
        print_fn("")
        for y in range(new_h):
            print_fn("".join("██" if px[x, y] < 128 else "  " for x in range(new_w)))
        print_fn("")
    except Exception:  # noqa: BLE001
        print_fn("(终端二维码渲染失败，请直接打开二维码图片)")


def open_image(path: Path) -> None:
    """Open an image on macOS (best-effort)."""
    try:
        subprocess.Popen(["open", str(path)])
    except Exception:  # noqa: BLE001
        pass


class WeReadLoginFlow:
    """Create a QR, show it, poll until scanned, persist the token."""

    def __init__(
        self,
        client: WeReadClient,
        qr_path: Path = Path("data/auth/weread_qrcode.png"),
    ) -> None:
        self.client = client
        self.qr_path = Path(qr_path)

    async def run(
        self,
        *,
        timeout: float = 120.0,
        on_qr: Optional[QrCallback] = None,
        print_fn: PrintCallback = print,
    ) -> WeReadLoginSession:
        uuid, scan_url = await self.client.create_login()
        self.qr_path.parent.mkdir(parents=True, exist_ok=True)
        if render_qr_png(scan_url, self.qr_path):
            if on_qr is not None:
                on_qr(self.qr_path)
            else:
                render_terminal_ascii(self.qr_path, print_fn=print_fn)
                open_image(self.qr_path)
        else:
            print_fn(f"二维码生成失败，请手动访问: {scan_url}")
        return await self.client.poll_login(uuid, timeout=timeout)
