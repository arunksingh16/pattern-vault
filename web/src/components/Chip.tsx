interface ChipProps {
  label: string
  active?: boolean
  variant?: 'primary' | 'secondary' | 'tertiary' | 'outline'
  onClick?: () => void
}

const variantStyles = {
  primary: 'bg-primary/15 text-primary border-primary/30',
  secondary: 'bg-secondary/15 text-secondary border-secondary/30',
  tertiary: 'bg-tertiary/15 text-tertiary border-tertiary/30',
  outline: 'bg-transparent text-on-surface-variant border-outline-variant/40',
}

export function Chip({ label, active, variant = 'outline', onClick }: ChipProps) {
  const base = 'inline-flex items-center px-2 py-0.5 rounded border font-mono text-[10px] uppercase tracking-wider transition-all'
  const style = active ? variantStyles.primary : variantStyles[variant]
  const interactive = onClick ? 'cursor-pointer hover:bg-primary/10 hover:text-primary active:scale-95' : ''

  return (
    <span className={`${base} ${style} ${interactive}`} onClick={onClick}>
      {label}
    </span>
  )
}
