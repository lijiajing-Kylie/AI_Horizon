interface EmptyStateProps {
  title: string
  description?: string
  icon?: React.ReactNode
  children?: React.ReactNode
}

export default function EmptyState({ title, description, icon, children }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-[var(--muted)]">
      {icon && <div className="mb-4">{icon}</div>}
      <h3 className="text-base font-medium text-[var(--ink)] mb-1">{title}</h3>
      {description && <p className="text-sm mb-5 max-w-[260px] text-center">{description}</p>}
      {children && <div className="flex items-center gap-3 flex-wrap justify-center">{children}</div>}
    </div>
  )
}
