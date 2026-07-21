interface EmptyStateProps {
  title: string
  description?: string
}

export default function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className="text-center py-10 text-[var(--muted)]">
      <h3 className="text-base font-medium text-[var(--ink)] mb-1">{title}</h3>
      {description && <p className="text-sm">{description}</p>}
    </div>
  )
}
