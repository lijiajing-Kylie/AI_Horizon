export default function LoadingSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      {[1, 2, 3].map(i => (
        <div key={i} className="border border-gray-200 rounded-lg p-5">
          <div className="h-5 bg-gray-200 rounded w-3/4 mb-3" />
          <div className="h-4 bg-gray-100 rounded w-full mb-2" />
          <div className="h-4 bg-gray-100 rounded w-2/3" />
        </div>
      ))}
    </div>
  )
}
