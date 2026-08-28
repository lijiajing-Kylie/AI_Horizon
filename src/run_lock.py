"""Prevent concurrent news-pipeline runs for the same run_date.

Running ``horizon`` twice for the same UTC day races on a shared SQLite
snapshot key: each run's step 4.1 does ``DELETE FROM items WHERE run_date=?``
before re-inserting, so a later process wipes the earlier one's rows and the
enrichment / selected flags become a nondeterministic last-writer-wins mix
(plus double AI spend and duplicate email/webhook notifications).

This module provides a flock-based advisory lock keyed by run_date. flock is
used instead of a pid file because the kernel releases the lock when the
owning process exits — including crashes — so no stale-lock cleanup is ever
needed. A second process fails fast instead of corrupting that day's data.
"""

import logging
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:  # pragma: no cover — non-POSIX platform (e.g. Windows)
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class RunLockError(RuntimeError):
    """Raised when the run_date lock is already held by another process."""


class RunLock:
    """Advisory ``flock`` on ``data/locks/horizon-<run_date>.lock``.

    The lock file may be left behind after a run — an unlocked file is
    harmless and ``acquire()`` simply re-opens and re-locks it. On platforms
    without ``fcntl`` the lock degrades to a no-op warning (fail-open: never
    block the pipeline because of a missing lock primitive).
    """

    def __init__(self, lock_dir: Path, run_date: str) -> None:
        self.lock_dir = Path(lock_dir)
        self.run_date = run_date
        self._fd: Optional[int] = None
        self._lock_path: Optional[Path] = None

    def acquire(self) -> Path:
        """Take an exclusive, non-blocking lock for ``run_date``.

        Returns the lock file path; raises :class:`RunLockError` if another
        process already holds the lock.
        """
        if fcntl is None:  # pragma: no cover — non-POSIX platform
            logger.warning(
                "fcntl unavailable — skipping run_date lock for %s (non-POSIX platform)",
                self.run_date,
            )
            return self.lock_dir
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.lock_dir / f"horizon-{self.run_date}.lock"
        fd = open(lock_path, "w")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()
            raise RunLockError(
                f"已有 horizon 进程正在运行同一天 ({self.run_date}),本实例退出。"
            ) from None
        self._fd = fd
        self._lock_path = lock_path
        return lock_path

    def release(self) -> None:
        """Release the lock if held. Idempotent and safe when never acquired."""
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                self._fd.close()
            self._fd = None

    @property
    def lock_path(self) -> Optional[Path]:
        return self._lock_path

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
