"""One-off backfill: add the 13 new LLM-era papers to the classic papers library.

Follows the same processing as the standard ``horizon-papers --source openalex``
flow — OpenAlex matching → AI translation → AI keywords → rule-based topic
classification → DB save. Unlike the CLI, it only processes the 13 newly-added
seeds (``NEW_TITLES`` below, matching ``seed_data.py``): the 50 existing classic
papers are re-matched against OpenAlex (free API) but never re-translated,
re-keyworded, or re-saved, so no AI budget is wasted on already-translated rows.

Run from the repo root:

    uv run python backfill_classic_papers.py --dry-run   # match only, no AI / no DB write
    uv run python backfill_classic_papers.py             # full backfill
    uv run python backfill_classic_papers.py --keywords-only
    # re-extract AI keywords for the new papers that are still missing them
    # (e.g. after a transient AI-provider outage mid-run)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from dotenv import load_dotenv

from src.ai.client import create_ai_client
from src.papers.keywords import _get_concurrency, extract_paper_keywords
from src.papers.models import Paper
from src.papers.sources.openalex import OpenAlexFetcher
from src.papers.topics import build_paper_topics, classify_paper_topics
from src.papers.translator import translate_papers
from src.storage.db import HorizonDB
from src.storage.manager import StorageManager

# The 13 new seeds added to src/papers/seed_data.py (matched by seed title).
NEW_TITLES = {
    "ReAct: Synergizing Reasoning and Acting in Language Models",
    "LLaMA: Open and Efficient Foundation Language Models",
    "Tree of Thoughts: Deliberate Problem Solving with Large Language Models",
    "Let's Verify Step by Step: Step-Level Verification of LLMs",
    "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
    "Visual Instruction Tuning",
    "Generative Agents: Interactive Simulacra of Human Behavior",
    "Llama 2: Open Foundation and Fine-Tuned Chat Models",
    "Mistral 7B",
    "QLoRA: Efficient Finetuning of Quantized Large Language Models",
    "Mixtral of Experts",
    "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?",
    "DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning",
}


async def _keywords_only(config) -> int:
    """Re-extract AI keywords for the 13 new papers that lack them.

    Scoped to the new papers (openalex source, publication_year >= 2022 — the
    pre-existing 50 classic papers are all <= 2020) so a transient AI-provider
    outage mid-backfill never bleeds extra AI spend onto old rows.
    """
    db = HorizonDB()
    result = db.get_papers(per_page=10000)
    new_rows = [
        r for r in result["items"]
        if r.get("source") == "openalex" and (r.get("publication_year") or 0) >= 2022
    ]
    missing = [r for r in new_rows if not r.get("keywords")]
    if not missing:
        print("所有新增论文都已有关键词。")
        return 0
    print(f"为 {len(missing)}/{len(new_rows)} 篇新增论文重新提取关键词...")
    papers = [Paper(**{k: v for k, v in r.items() if k != "topics"}) for r in missing]
    ai_client = create_ai_client(config.ai)
    await extract_paper_keywords(ai_client, papers, _get_concurrency(ai_client))
    saved = db.save_papers(papers)
    failed = [p for p in papers if not p.keywords]
    print(f"保存 {saved} 篇；仍有 {len(failed)} 篇关键词为空。")
    for p in papers:
        print(f"  {p.id}: {p.keywords}")
    return saved


async def main(dry_run: bool, keywords_only: bool) -> int:
    load_dotenv()
    config = StorageManager(data_dir="data").load_config()
    if not config.papers or not config.papers.enabled:
        print("papers library not enabled in config")
        return 1
    papers_cfg = config.papers
    if not papers_cfg.openalex.enabled:
        print("openalex source not enabled in config")
        return 1

    if keywords_only:
        return await _keywords_only(config)

    db = HorizonDB() if not dry_run else None

    print("Matching all classic seeds against OpenAlex (existing 50 are only "
          "matched, never re-translated)...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        result = await OpenAlexFetcher(papers_cfg.openalex).fetch_classic(client)

    # Relate match_results ↔ papers by paper_id (papers list may exclude None).
    paper_by_id = {p.id: p for p in result.papers if p.id}
    new_matched: list = []
    new_failed: list = []
    for mr in result.match_results:
        if mr.seed_title not in NEW_TITLES:
            continue
        if mr.match_status == "matched" and mr.paper_id and mr.paper_id in paper_by_id:
            new_matched.append(paper_by_id[mr.paper_id])
        else:
            new_failed.append(mr)

    # ---- per-seed match report -------------------------------------------
    print(f"\n新增 seed 匹配结果: matched {len(new_matched)}, "
          f"manual_review/unmatched {len(new_failed)}")
    for mr in result.match_results:
        if mr.seed_title not in NEW_TITLES:
            continue
        status = {"matched": "✓", "manual_review": "?", "unmatched": "✗"}.get(
            mr.match_status, mr.match_status
        )
        print(f"  [{status}] {mr.seed_title}")
        print(f"      -> {mr.matched_title or '—'} ({mr.matched_year or '—'})  "
              f"method={mr.match_method or '—'}  note={mr.note}")

    if new_failed:
        print("\n以下新增 seed 未匹配，需人工核查 arXiv ID 后重跑：")
        for mr in new_failed:
            print(f"  - {mr.seed_title} [{mr.match_status}] {mr.note}")
        return 1

    if dry_run:
        print("\n[dry-run] 13/13 全部匹配，未调用 AI、未写库。"
              "正式运行将对这 13 篇做翻译 + 关键词 + 主题分类 + 保存。")
        return 0

    # ---- process only the newly matched papers ---------------------------
    ai_client = create_ai_client(config.ai)
    concurrency = _get_concurrency(ai_client)

    print(f"\n翻译为中文（{len(new_matched)} 篇）...")
    await translate_papers(ai_client, new_matched)

    if papers_cfg.extract_keywords:
        print(f"提取 AI 关键词（{len(new_matched)} 篇）...")
        await extract_paper_keywords(ai_client, new_matched, concurrency)

    saved = db.save_papers(new_matched)
    print(f"保存到 papers 表：{saved} 篇")

    # Topic classification (rule-based, zero AI cost)
    db.seed_paper_topics(build_paper_topics())
    tc = 0
    for paper in new_matched:
        td = classify_paper_topics(paper)
        if td:
            db.save_paper_topics(paper.id, td)
            tc += 1
    print(f"主题映射分类：{tc}/{len(new_matched)} 篇")

    # ---- summary report --------------------------------------------------
    print("\n-- 入库结果 --")
    for p in sorted(new_matched, key=lambda x: x.publication_year):
        print(f"- {p.title[:70]}")
        print(f"    id={p.id}  year={p.publication_year}  category={p.category}")
        print(f"    venue={p.journal_ref}")
        print(f"    title_zh={p.title_zh!r}")
        print(f"    keywords={p.keywords}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill 13 new LLM-era classic papers into the library"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Match against OpenAlex only — no AI calls, no DB write",
    )
    parser.add_argument(
        "--keywords-only",
        action="store_true",
        help="Re-extract AI keywords for the new papers missing them, then exit",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.dry_run, args.keywords_only)))
