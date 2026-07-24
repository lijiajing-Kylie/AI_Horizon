interface CardHeadingProps {
  children: React.ReactNode
}

/** Section heading inside a glass card — small tracked-out eyebrow label. */
export default function CardHeading({ children }: CardHeadingProps) {
  return (
    <h2 className="text-[11px] font-bold tracking-[.14em] text-[#8ea0b6] mb-3">
      {children}
    </h2>
  )
}
