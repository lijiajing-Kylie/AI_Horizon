"""Shared console output helpers for the papers pipeline CLI.

The papers AI stages (scoring, enrichment, translation, keyword extraction)
run as batched concurrent AI calls that can take minutes with zero feedback.
``run_progress`` wraps those batches in a single-line progress bar so the
terminal shows the pipeline is alive. In non-interactive environments (CI /
redirected output) the bar is hidden and only a summary line is printed, so
it never floods the log.
"""

import asyncio
from typing import Awaitable, List

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
)

console = Console()


async def run_progress(description: str, coros: List[Awaitable]) -> List:
    """Run ``coros`` concurrently behind a single-line progress bar.

    Returns results in input order (mirrors ``asyncio.gather``). Empty input
    returns ``[]`` without touching the console.
    """
    if not coros:
        return []

    tasks = [asyncio.create_task(c) for c in coros]

    if not console.is_terminal:
        await asyncio.gather(*tasks)
        console.print(f"   {description}: {len(tasks)} 完成")
        return [t.result() for t in tasks]

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(description, total=len(tasks))
        for done in asyncio.as_completed(tasks):
            await done
            progress.update(task_id, advance=1)

    return [t.result() for t in tasks]
