interface EmptyStateProps {
  icon?: string
  title: string
  description?: string
}

export default function EmptyState({ icon = '📭', title, description }: EmptyStateProps) {
  return (
    <div className="text-center py-16 text-gray-400">
      <div className="text-4xl mb-3">{icon}</div>
      <h3 className="text-lg font-medium text-gray-500 mb-1">{title}</h3>
      {description && <p className="text-sm">{description}</p>}
    </div>
  )
}
