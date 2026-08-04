"""One-off backfill: re-extract keywords for a single paper (Chinese-first).

DeepSeek caches responses for identical user payloads, so the shared
``KEYWORDS_USER`` template can keep returning an old English result even after
the language policy changes. This script instead calls the model directly with
a strong Chinese-first prompt (proper nouns may keep English), then writes only
the ``keywords`` field back.

Run from the repo root:

    uv run python backfill_keywords_oneoff.py <paper_id>
"""

from __future__ import annotations

import asyncio
import sys

from dotenv import load_dotenv

from src.ai.client import create_ai_client
from src.ai.utils import parse_json_response
from src.papers.models import Paper
from src.storage.db import HorizonDB
from src.storage.manager import StorageManager

PROMPT_SYSTEM = """你是学术编辑。根据论文标题、分类与摘要，提取 3-5 个关键词，全部必须使用简体中文。
通用术语必须翻译成中文：compound options 写"复合期权"，multi-stage real options 写"多阶段实物期权"，
recursive valuation 写"递归估值"，analytic coefficients 写"解析系数"。
只有没有中文译法的专有名词可保留英文：如 COS方法、Lévy过程、Transformer。
禁止整条列表都是英文。只返回合法 JSON，不要 markdown。"""


def _user_prompt(paper: Paper, salt: str) -> str:
    return f"""标题：{paper.title}
分类：{", ".join(paper.categories)}
摘要：{(paper.abstract or "")[:2000]}

仅返回 JSON：
{{"keywords": ["中文关键词1", "中文关键词2", ...]}}

（请求编号：{salt}）"""


async def main(paper_id: str) -> int:
    load_dotenv()
    config = StorageManager(data_dir="data").load_config()
    if not config.papers or not config.papers.enabled:
        print("papers library not enabled in config")
        return 1

    db = HorizonDB()
    row = db.get_paper(paper_id)
    if not row:
        print(f"paper {paper_id!r} not found")
        return 1
    row.pop("topics", None)  # attached by get_paper, not a Paper model field

    paper = Paper(**row)
    print(f"re-extracting keywords for: {paper.title}")

    ai_client = create_ai_client(config.ai)
    keywords: list[str] = []
    response = ""
    for attempt in range(3):
        # A per-attempt salt keeps the user payload unique so DeepSeek's
        # response cache for repeated identical requests is not hit, and a
        # transient empty/unparseable response is retried.
        response = await ai_client.complete(
            system=PROMPT_SYSTEM,
            user=_user_prompt(paper, f"backfill-{attempt}"),
            temperature=0.2,
            max_tokens=300,
        )
        result = parse_json_response(response)
        keywords = (
            [str(k).strip() for k in result["keywords"][:5] if str(k).strip()]
            if result and result.get("keywords")
            else []
        )
        if keywords:
            break
        print(f"  attempt {attempt}: empty/unparseable response={response!r}, retrying")
    if not keywords:
        print("keyword extraction failed — DB untouched")
        return 1

    paper.keywords = keywords
    db.save_papers([paper])
    print(f"keywords -> {paper.keywords}")
    return 0


if __name__ == "__main__":
    paper_id = sys.argv[1] if len(sys.argv) > 1 else "arxiv_fin:2607.25599"
    raise SystemExit(asyncio.run(main(paper_id)))
