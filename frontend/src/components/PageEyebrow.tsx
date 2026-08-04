interface PageEyebrowProps {
  children: React.ReactNode
}

/** Page-level eyebrow label above the h1 title — e.g. REPORTS, PAPERS, SEARCH. */
export default function PageEyebrow({ children }: PageEyebrowProps) {
  return (
    <p className="text-[11px] font-bold tracking-[.21em] text-[var(--eyebrow)] mb-2">
      {children}
    </p>
  )
}
