interface CardHeadingProps {
  children: React.ReactNode
}

/** Section heading inside a glass card — small tracked-out eyebrow label. */
export default function CardHeading({ children }: CardHeadingProps) {
  return (
    <h2 className="text-[11px] font-bold tracking-[.14em] text-[var(--eyebrow)] mb-3">
      {children}
    </h2>
  )
}
