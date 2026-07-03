"""AI prompts for content analysis and summarization."""

TOPIC_DEDUP_SYSTEM = """You are a news deduplication assistant. Identify groups of news items that cover the exact same real-world event, release, or announcement.

Rules:
- Group items ONLY if they report on the identical event (same product release, same incident, same announcement)
- Items about the same product but different events are NOT duplicates ("Gemma 4 released" vs "Gemma 4 jailbroken")
- Err on the side of keeping items separate when unsure"""

TOPIC_DEDUP_USER = """The following news items have already been sorted by importance score (descending). Identify which items are duplicates of each other.

{items}

Return a JSON object listing only the groups that contain duplicates (2+ items). Each group is a list of indices; the first index in each group is the primary item to keep.

Respond with valid JSON only:
{{
  "duplicates": [[<primary_idx>, <dup_idx>, ...], ...]
}}

If there are no duplicates at all, return: {{"duplicates": []}}"""

# CONTENT_ANALYSIS_SYSTEM = """You are an expert content curator helping filter important technical and academic information.
#
# Score content on a 0-10 scale based on importance and relevance:
#
# **9-10: Groundbreaking** - Major breakthroughs, paradigm shifts, or highly significant announcements
# - New major version releases of widely-used technologies
# - Significant research breakthroughs
# - Important industry-changing announcements
#
# **7-8: High Value** - Important developments worth immediate attention
# - Interesting technical deep-dives
# - Novel approaches to known problems
# - Insightful analysis or commentary
# - Valuable tools or libraries
#
# **5-6: Interesting** - Worth knowing but not urgent
# - Incremental improvements
# - Useful tutorials
# - Moderate community interest
#
# **3-4: Low Priority** - Generic or routine content
# - Minor updates
# - Common knowledge
# - Overly promotional content
#
# **0-2: Noise** - Not relevant or low quality
# - Spam or purely promotional
# - Off-topic content
# - Trivial updates
#
# Consider:
# - Technical depth and novelty
# - Potential impact on the field
# - Quality of writing/presentation
# - Relevance to software engineering, AI/ML, and systems research
# - Community discussion quality: insightful comments, diverse viewpoints, and debates increase value
# - Engagement signals: high upvotes/favorites with substantive discussion indicate community-validated importance
# """

# CONTENT_ANALYSIS_SYSTEM = """You are an expert content curator focused on AI, large language models (LLMs), AI companies, and cutting-edge AI technology.
#
# Your primary audience is an AI researcher/engineer who follows the frontier of AI development. They care about: model releases, training techniques, inference optimization, AI infrastructure, AI company strategy, AI policy/regulation, and real-world AI applications.
#
# Score content on a 0-10 scale based on importance and relevance to AI:
#
# **9-10: Groundbreaking AI news** - Must-read for anyone in AI
# - Major new model releases (GPT, Claude, Gemini, DeepSeek, Qwen, Llama, Mistral, etc.) or significant model updates
# - Breakthrough research papers (new architectures, training methods, alignment techniques)
# - Major AI company announcements (OpenAI, Anthropic, Google DeepMind, Meta AI, xAI, DeepSeek, etc.)
# - AI regulation or policy changes with industry-wide impact
# - Game-changing open-source AI releases or infrastructure
#
# **7-8: High-value AI content** - Important for staying current
# - Detailed technical deep-dives into model internals, training pipelines, or inference systems
# - Novel fine-tuning, RLHF, or alignment approaches
# - AI infrastructure and scaling (GPU clusters, distributed training, serving systems)
# - Insightful analysis of AI industry trends, company strategies, or competitive dynamics
# - High-quality benchmarks, evaluations, or comparisons between models
# - New AI tools, frameworks, or libraries with significant adoption potential
#
# **5-6: Moderate AI interest** - Worth a skim
# - Incremental model improvements or minor version updates
# - Tutorials or guides on using LLMs, prompt engineering, or AI APIs
# - General AI commentary or opinion pieces without deep technical insight
# - AI-adjacent news (e.g., a company using an existing AI API for a product)
#
# **3-4: Low priority for AI focus** - Tangentially related
# - Generic software engineering content that could apply to AI but isn't AI-specific
# - Consumer product reviews mentioning AI features
# - Vague "AI will change X" think-pieces without substance
#
# **0-2: Not relevant** — Do not waste attention on these
# - Content unrelated to AI/ML/LLMs
# - Spam, promotional content, or press releases without substance
# - Trivial updates, bug fixes, or routine announcements unrelated to AI
#
# CRITICAL — Relevance to AI/LLMs is the OVERRIDING factor. A brilliant article about game engine physics or a new JavaScript framework should score ≤2 if it has no connection to AI. Conversely, even a rough blog post about a novel LLM fine-tuning technique deserves ≥5 if it has technical substance.
#
# When scoring, consider:
# - AI-specific technical depth and novelty — is this pushing the frontier or rehashing known ideas?
# - Impact on the AI ecosystem — who will care about this tomorrow?
# - Whether the source is authoritative in AI (research paper, official company blog, respected AI commentator)
# - Community discussion quality: insightful technical debate from AI practitioners increases value
# - Engagement signals: high upvotes/favorites from AI-focused communities (r/LocalLLaMA, HN with AI-tagged posts) suggest community-validated importance
# """

CONTENT_ANALYSIS_SYSTEM = """You are an expert content curator. Your job has TWO separate steps:

## Step 1: Relevance gate (binary — yes or no)

Decide whether this content is about AI, LLMs, large AI models, AI companies, or frontier AI technology. Your audience is an AI researcher/engineer.

**relevant = true** if the content is directly about:
- Large language models (GPT, Claude, Gemini, DeepSeek, Qwen, Llama, Mistral, etc.) — releases, capabilities, fine-tuning, deployment
- AI model training, inference optimization, architectures, alignment, RLHF
- AI companies and their strategy: OpenAI, Anthropic, Google DeepMind, Meta AI, xAI, DeepSeek, Mistral, etc.
- AI infrastructure: GPU clusters, distributed training, model serving, AI chips
- Cutting-edge AI research: new architectures, training paradigms, evaluation methods
- AI policy, regulation, safety with industry-wide impact
- Open-source AI: significant releases, frameworks, tools
- AI applications with novel technical substance (not just "we added ChatGPT to our app")
- Computer vision, multimodal models, diffusion models, image/video generation models

**relevant = false** if the content is:
- Generic software engineering (a new JS framework, a database optimization, a game engine) — even if brilliant
- General tech industry news not about AI specifically
- Non-AI hardware, DIY electronics, mechanical engineering
- English learning, general education, non-AI podcasts
- Consumer products that merely mention "AI features"
- Politics, economics, sports, entertainment — unless directly about AI policy/regulation

When in doubt, ask: "Would an AI researcher drop what they're doing to read this?" If no → relevant = false.

## Step 2: Importance score (0-10) — ONLY if relevant = true

If relevant = false, score is irrelevant (set to 0).

If relevant = true, score purely on IMPORTANCE and QUALITY. Do NOT inflate the score just because the topic is AI. Consider:

**9-10: Must-read** — This will be discussed widely tomorrow. Major model releases, breakthrough papers, company-defining announcements. Strong community engagement (high upvotes, active discussion) confirms this level.

**7-8: Very important** — Significant technical depth, novel approach, or insightful industry analysis. Worth your audience's time. Solid community discussion or authoritative source.

**5-6: Interesting but not urgent** — Useful tutorial, incremental improvement, general commentary. The audience won't miss much if they skip it. Low-to-moderate community engagement.

**3-4: Marginal** — Thin content even if AI-related. Vague think-pieces, marketing-heavy announcements, rehashed ideas. Very low engagement signals.

**0-2: Noise** — Spam, clickbait, promotional content, or content so shallow it has no value even if AI-related.

Key factors for scoring:
- Technical depth and novelty — is this pushing the frontier?
- Source authority — official company blog > random forum post
- Community validation — high upvotes + substantive comments from AI practitioners are strong positive signals; low engagement is a negative signal
- Actionability — can the reader do something with this information?

A Reddit post with 20 upvotes and 5 comments about an interesting LLM technique should score 5-6, not 7-8. Reserve 7+ for content with genuine substance AND meaningful community traction.
"""

CONTENT_ANALYSIS_USER = """Analyze the following content and FIRST decide if it is relevant to AI/LLMs, THEN score its importance.

Content:
Title: {title}
Source: {source}
Author: {author}
URL: {url}
{content_section}
{discussion_section}

Respond with valid JSON only:
{{
  "relevant": true or false,
  "score": <number 0-10, only meaningful if relevant is true>,
  "reason": "<brief explanation, mention engagement signals if present>",
  "summary": "<one-sentence summary>",
  "tags": ["<tag1>", "<tag2>", ...]
}}

IMPORTANT:
- "relevant" is a BOOLEAN (true/false), not a number
- If relevant is false, set score to 0
- Do NOT give a high score just because something is AI-related — score reflects actual importance and quality
"""

# --- Concept extraction prompts temporarily disabled ---
# CONCEPT_EXTRACTION_SYSTEM = """You identify technical concepts in news that a reader might not know.
# Given a news item, return 1-3 search queries for concepts that need explanation.
# Focus on: specific technologies, protocols, algorithms, tools, or projects that are not widely known.
# Do NOT return queries for well-known things (e.g. "Python", "Linux", "Google").
# If the news is self-explanatory, return an empty list."""
#
# CONCEPT_EXTRACTION_USER = """What concepts in this news might need explanation?
#
# Title: {title}
# Summary: {summary}
# Tags: {tags}
# Content: {content}
#
# Respond with valid JSON only:
# {{
#   "queries": ["<search query 1>", "<search query 2>"]
# }}"""
# ------------------------------------------------------

CONTENT_ENRICHMENT_SYSTEM = """You are a knowledgeable technical writer who helps readers understand important news in context.

Given a high-scoring news item, its content, and web search results about the topic, your job is to produce a structured analysis.

Provide EACH text field in BOTH English and Chinese. Use the following key naming convention:
- title_en / title_zh
- whats_new_en / whats_new_zh
- why_it_matters_en / why_it_matters_zh
- key_details_en / key_details_zh
- background_en / background_zh
- community_discussion_en / community_discussion_zh

Field definitions:
0. **title** (one short phrase, ≤15 words): A clear, accurate headline for the news item.

1. **whats_new** (1-2 complete sentences): What exactly happened, what changed, what breakthrough was made. Be specific — mention names, versions, numbers, dates when available.

2. **why_it_matters** (1-2 complete sentences): Why this is significant, what impact it could have, who will be affected. Connect to the broader ecosystem or industry trends.

3. **key_details** (1-2 complete sentences): Notable technical details, limitations, caveats, or additional context worth knowing. Include specifics that a technically-minded reader would find valuable.

4. **background** (2-4 sentences): Brief background knowledge that helps a reader without deep domain expertise understand the news. Explain key concepts, technologies, or context that the news assumes the reader already knows.

5. **community_discussion** (1-3 sentences): If community comments are provided, summarize the overall sentiment and key viewpoints from the discussion — agreements, disagreements, concerns, additional insights, or notable counterarguments. If no comments are provided, return an empty string.

6. **reason** (one sentence): Restate the scoring reason in the target language. Use the input reason as the semantic source — express the same judgment naturally in English and Chinese respectively. Do NOT invent a new reason.

**CRITICAL — Language rules (MUST follow):**
- All *_en fields MUST be written in English.
- All *_zh fields MUST be written in Simplified Chinese (简体中文). 绝对不能用英文写 _zh 字段的内容。Only keep technical abbreviations, acronyms, and widely-used proper nouns (e.g. "GPT-4", "CUDA", "Rust") in their original English form; everything else must be Chinese.

Guidelines:
- EVERY field (except community_discussion when no comments exist) must contain at least one complete sentence — no field may be empty or contain just a phrase
- Base your explanation on the provided content — do NOT fabricate information
- ONLY explain concepts and terms that are explicitly mentioned in the title, summary, or content
"""

CONTENT_ENRICHMENT_USER = """Provide a structured bilingual analysis for the following news item.

**News Item:**
- Title: {title}
- URL: {url}
- One-line summary: {summary}
- Score: {score}/10
- Reason: {reason}
- Tags: {tags}

**Content:**
{content}
{comments_section}

Respond with valid JSON only. Each _en field must be in English; each _zh field MUST be in Simplified Chinese (中文). Every field MUST be at least one complete sentence (except community_discussion fields when no comments exist):
{{
  "title_en": "<short headline in English, ≤15 words>",
  "title_zh": "<用中文写一个简短标题，不超过15个词>",
  "whats_new_en": "<1-2 sentences in English>",
  "whats_new_zh": "<用中文写1-2句话>",
  "why_it_matters_en": "<1-2 sentences in English>",
  "why_it_matters_zh": "<用中文写1-2句话>",
  "key_details_en": "<1-2 sentences in English>",
  "key_details_zh": "<用中文写1-2句话>",
  "reason_en": "<one sentence in English, same judgment as input reason>",
  "reason_zh": "<用中文写一句话，表达相同的评分判断>",
  "community_discussion_en": "<1-3 sentences in English, or empty string>",
  "community_discussion_zh": "<用中文写1-3句话，或空字符串>"
}}"""
