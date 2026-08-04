export default function LoadingSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      {[1, 2, 3].map(i => (
        <div key={i} className="glass rounded-2xl p-5">
          <div className="h-5 bg-black/[.06] rounded w-3/4 mb-3" />
          <div className="h-4 bg-black/[.04] rounded w-full mb-2" />
          <div className="h-4 bg-black/[.04] rounded w-2/3" />
        </div>
      ))}
    </div>
  )
}
