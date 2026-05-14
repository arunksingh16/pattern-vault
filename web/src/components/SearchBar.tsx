import { useEffect, useRef, useState } from 'react'

interface SearchBarProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  debounceMs?: number
}

export function SearchBar({ value, onChange, placeholder = 'Search patterns...', debounceMs = 300 }: SearchBarProps) {
  const [local, setLocal] = useState(value)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    setLocal(value)
  }, [value])

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value
    setLocal(v)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => onChange(v), debounceMs)
  }

  function handleClear() {
    setLocal('')
    onChange('')
  }

  return (
    <div className="flex items-center gap-3 bg-surface-container-lowest border border-outline-variant/30 rounded-xl px-4 py-2.5 focus-within:border-primary/50 transition-colors">
      <span className="material-symbols-outlined text-[18px] text-outline">search</span>
      <input
        type="text"
        value={local}
        onChange={handleChange}
        placeholder={placeholder}
        className="flex-1 bg-transparent text-on-surface font-mono text-code-sm outline-none placeholder:text-on-surface-variant/50"
      />
      {local && (
        <button onClick={handleClear} className="text-outline hover:text-on-surface transition-colors">
          <span className="material-symbols-outlined text-[16px]">close</span>
        </button>
      )}
    </div>
  )
}
