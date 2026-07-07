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
