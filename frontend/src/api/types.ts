// ---- Items ----

export interface SourceAttribution {
  count: number
  labels: string[]
  detail: { label: string; title: string; url: string }[]
}

export interface SourceProvenanceEntry {
  source_name: string
  source_url: string
  source_type: string
  role: string
  title: string
  published_at: string | null
  is_primary: boolean
  discovered_via: string
  confidence: number
}

export interface SourceProvenance {
  primary_source_name: string
  primary_source_url: string
  primary_source_type: string
  source_count: number
  sources: SourceProvenanceEntry[]
}

export interface ContentLangBlock {
  title: string
  summary: string
  reason: string
  community_discussion: string
}

export interface ContentBlock {
  original_language: string
  default_language: string
  is_ai_translated: boolean
  content: Record<string, ContentLangBlock>
  enrichment_sources: EnrichmentSource[]
  discussion_url?: string
  source_provenance?: SourceProvenance
  source_attribution?: SourceAttribution
}

export interface EnrichmentSource {
  url: string
  title: string
}

export interface ScoreBreakdown {
  total: number
  source_authority: number
  novelty: number
  technical_substance: number
  real_world_impact: number
  community_validation: number
  content_completeness: number
  marketing_penalty: number
  duplicate_penalty: number
  thin_content_penalty: number
  weak_ai_relevance_penalty: number
  multi_source_bonus?: number
}

export interface Topic {
  id: number
  name: string
  slug: string
  group_name: string
  description: string
  confidence?: number
  reason?: string
  count?: number
}

export interface ArticleImage {
  url: string
  alt: string
  caption: string
  source: string
}

export interface NewsItem {
  id: string
  source_type: string
  title: string
  url: string
  content: string | null
  raw_content: string | null
  clean_content: string | null
  raw_html: string | null
  display_html: string | null
  display_html_zh: string | null
  cover_image: string | null
  images: ArticleImage[]
  author: string | null
  published_at: string
  fetched_at: string
  ai_relevant: boolean | null
  ai_score: number | null
  ai_reason: string | null
  ai_summary: string | null
  ai_tags: string[]
  metadata: Record<string, any>
  topics: Topic[]
  run_date: string
  content_block?: ContentBlock
  debug?: ScrapeDiagnostics
  /** Only present when the request carried X-User-Id (see utils/userId.ts). */
  is_favorited?: boolean
}

// ---- Scrape diagnostics (dev-only) ----
// Mirrors the grouped shape built by `_build_debug_block()` in
// src/api/server.py. Only ever present when the request was made with
// `include_debug=true` AND the API is running with HORIZON_API_ENV=development.

export interface DiagnosticsSource {
  original_title: string | null
  original_url: string | null
  rss_summary: string | null
  source_name: string | null
  published_at: string | null
}

export interface DiagnosticsFetch {
  http_status: number | null
  content_type: string | null // never populated today — not persisted upstream
  final_url: string | null
  extraction_status: string | null
  extraction_error: string | null
  content_source: string | null
  text_length: number | null
  extracted_at: string | null
  extractor_version: string | null
}

// Shared shape for both the analysis and enrichment stage previews.
export interface DiagnosticsStageInput {
  input: string | null
  input_length: number
  content_source: string | null
  original_length: number
  sent_length: number
  truncation_limit: number | null
  source_note: string
}

export type TranslationStatus =
  | 'success'
  | 'skipped_already_chinese'
  | 'failed'
  | 'fallback_to_original'
  | 'not_attempted'
  | 'empty_input'

export interface DiagnosticsTranslation {
  status: TranslationStatus
  source: string
  input: string | null
  input_length: number
  output: string | null
  output_length: number
  error: string | null // always null today — translate_display_html() never persists a failure reason
  skipped_reason: string | null
}

export interface ScrapeDiagnostics {
  source: DiagnosticsSource
  fetch: DiagnosticsFetch
  raw_html: string | null
  raw_html_length: number
  raw_content: string | null
  raw_content_length: number
  clean_content: string | null
  clean_content_length: number
  display_html: string | null
  display_html_length: number
  display_html_zh: string | null
  display_html_zh_length: number
  analysis: DiagnosticsStageInput
  enrichment: DiagnosticsStageInput
  translation: DiagnosticsTranslation
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  pages: number
}

/** 报告库分页响应：额外携带报告库最近一次抓取时间（UTC ISO）。 */
export interface ReportsResponse extends PaginatedResponse<Report> {
  latest_fetched_at?: string
}

// ---- Tags & Categories ----

export interface TagCount {
  tag: string
  count: number
}

export interface CategoryCount {
  category: string
  count: number
}

// ---- Topics ----

export interface TopicGroup {
  group_name: string
  topics: Topic[]
}

export interface TopicsResponse {
  groups: TopicGroup[]
}

export interface TopicDetail {
  id: number
  name: string
  slug: string
  group_name: string
  description: string
}

export interface TopicNewsResponse {
  topic: TopicDetail | null
  items: NewsItem[]
  total: number
  page: number
  per_page: number
  pages: number
}

// ---- Favorites & topic preferences ----

export type TopicPrefState = 'subscribed' | 'blocked'

export interface TopicPrefs {
  subscribed: string[]
  blocked: string[]
}

// ---- Daily ----

export interface DailyReport {
  date: string
  total_fetched: number
  total_selected: number
  languages: string[]
}

export interface DailyListResponse {
  reports: DailyReport[]
}

export interface DailyDetailResponse {
  date: string
  stats: Stats
  tags: TagCount[]
  topics: TopicsResponse
  items: NewsItem[]
  total: number
}

// ---- Stats ----

export interface Stats {
  total_items: number
  avg_score: number | null
  max_score: number | null
  source_types: number
}

// ---- Runs ----

export interface Run {
  date: string
  total_fetched: number
  total_selected: number
  languages: string[]
  created_at: string
}

// ---- Papers ----
// Standalone papers library (OpenAlex + arXiv sources) — no AI
// score/enrichment fields, unlike NewsItem.

export interface ReportPdf {
  name: string
  url: string
  local_path?: string
  /**
   * Entry type marker.  ``"direct"`` (default) is a regular PDF link; any
   * entry without a ``type`` field is treated as direct for backward
   * compatibility.
   */
  type?: string
}

export interface Report {
  id: string
  source: string
  native_id: string
  title: string
  institution: string
  institutions: string[]
  author: string | null
  url: string
  pdf_urls: ReportPdf[]
  summary: string | null
  content_text: string
  /** 原始 HTML（如微信文章正文），未清洗；仅 wxmp 源有值 */
  raw_html: string | null
  /** nh3 清洗后的微信正文 HTML（表格/图片/标题层级/段落）；仅 wxmp 源有值，可直接渲染 */
  display_html: string | null
  categories: string[]
  /** AI-extracted keywords (5-8), bilingual; 展示用，不用于过滤 */
  keywords: string[]
  published_at: string
  updated_at: string
  view_count: number | null
  download_count: number | null
  fetched_at: string
  /** 1-5 AI filter score; null when never evaluated (scored as neutral). */
  ai_relevance_score: number | null
  /** 0-1 综合分（0.5×AI 相关 + 0.5×篇幅）；仅用于排序，不展示数值。 */
  composite_score: number | null
  /** Whether at least one PDF has been downloaded and is served locally. */
  has_local_pdf?: boolean
  /** Only present when the request carried X-User-Id (see utils/userId.ts). */
  is_favorited?: boolean
}

export interface PaperTopic {
  id: number
  name: string
  slug: string
  group_name: string
  description: string
  confidence?: number
  reason?: string
}

export interface PaperLayeredSummary {
  one_sentence_summary?: string
  /** 合并后的「背景与问题」（v3 起）。旧行可能只有 background/previous_problem。 */
  background_problem?: string
  /** 旧字段，v3 之前存在；新行不再输出。 */
  background?: string
  previous_problem?: string
  core_idea?: string
  technical_details?: string
  experimental_evidence?: string
  real_world_impact?: string
  limitations?: string
  /** Editorial innovation grading: level ∈ {breakthrough, significant_improvement, incremental, engineering}. */
  innovation_level?: { level: string; reason?: string }
  /** Interpretation-format version; bumped when AI prompt semantics change. */
  interpretation_version?: number
  /** Legacy field present on pre-monolingual (bilingual) data only. */
  key_details?: string
}

export interface PaperScoreBreakdown {
  innovation?: number
  technical_quality?: number
  impact_potential?: number
  relevance?: number
}

export interface Paper {
  id: string
  source: string
  native_id: string
  title: string
  authors: string[]
  abstract: string
  url: string
  pdf_url: string | null
  published_at: string
  updated_at: string
  publication_year: number | null
  categories: string[]
  category: string | null
  comment: string | null
  journal_ref: string | null
  doi: string | null
  arxiv_id: string | null
  open_access: boolean | null
  citation_count: number | null
  citation_percentile: number | null
  upvote_count: number | null
  fetched_at: string
  /** AI-translated Chinese title (null when not yet translated). */
  title_zh: string | null
  /** AI-translated Chinese abstract (null when not yet translated). */
  abstract_zh: string | null
  /** Detected source language: "zh", "en", or "unknown". */
  original_language: string | null
  /** Assigned research-direction topics (from rule-based classification). */
  topics?: PaperTopic[]
  /** Only present when the request carried X-User-Id (see utils/userId.ts). */
  is_favorited?: boolean

  // ── Featured / AI-enriched fields（arXiv 精选 + AI 解读）─────────────────
  /** 期刊 / 会议名。 */
  venue?: string | null
  /** 是否被精选板块（AI+金融 / 最新论文）收录。 */
  is_featured?: boolean
  /** AI 解读摘要：新格式为分层 PaperLayeredSummary，旧数据为 { zh } 双语包装。 */
  ai_summary?: (PaperLayeredSummary & { zh?: PaperLayeredSummary }) | null
  /** AI 评分分项（创新性 / 技术质量 / 潜在影响 / AI 关注度）。 */
  ai_score_breakdown?: PaperScoreBreakdown | null
  /** AI 相关度综合评分（0–10）。 */
  ai_relevance_score?: number | null
  /** 精选板块（AI+金融 / 最新论文）的 featured 日期。 */
  featured_date?: string | null
  /** 关键词（展示用，经典论文可能为空）。 */
  keywords?: string[]
  /** GitHub 仓库链接（若论文开源）。 */
  github_url?: string | null
}

// ---- Global Search -------------------------------------------------------

export interface GlobalSearchSection<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  pages: number
}

export interface GlobalSearchResponse {
  news: GlobalSearchSection<NewsItem>
  papers: GlobalSearchSection<Paper>
  reports: GlobalSearchSection<Report>
}
