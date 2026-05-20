import { Chip } from '@/components/Chip'

interface FilterChipsProps {
  items: string[]
  selected: string | null
  onSelect: (value: string | null) => void
  variant?: 'primary' | 'secondary' | 'tertiary'
}

export function FilterChips({ items, selected, onSelect, variant = 'primary' }: FilterChipsProps) {
  if (items.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1.5">
      {selected && (
        <Chip
          label="All"
          variant="outline"
          onClick={() => onSelect(null)}
        />
      )}
      {items.map((item) => (
        <Chip
          key={item}
          label={item}
          active={item === selected}
          variant={variant}
          onClick={() => onSelect(item === selected ? null : item)}
        />
      ))}
    </div>
  )
}
