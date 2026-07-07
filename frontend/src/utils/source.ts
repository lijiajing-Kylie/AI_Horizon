import type { NewsItem } from '../api/types'

const SOURCE_LABELS: Record<string, string> = {
  github: 'GitHub',
  hackernews: 'Hacker News',
  rss: 'RSS',
  reddit: 'Reddit',
  telegram: 'Telegram',
  twitter: 'Twitter/X',
  openbb: 'OpenBB',
  ossinsight: 'OSS Insight',
  gdelt: 'GDELT',
  google_news: 'Google News',
}

export function sourceLabel(item: NewsItem): string {
  const meta = item.metadata
  if (meta?.feed_name) return meta.feed_name
  if (meta?.subreddit) return `r/${meta.subreddit}`
  if (meta?.channel) return `@${meta.channel}`
  return SOURCE_LABELS[item.source_type] || item.source_type
}

export const ROLE_LABELS_ZH: Record<string, string> = {
  official_company_blog: '官方博客',
  official_product_page: '官方产品页',
  official_model_page: '官方模型页',
  paper: '论文',
  media_report: '媒体报道',
  expert_blog: '专家博客',
  social_post: '社交媒体',
  community_discussion: '社区讨论',
  aggregator: '聚合站',
  unknown: '其他',
}

export function roleLabelZh(role: string): string {
  return ROLE_LABELS_ZH[role] || role
}
