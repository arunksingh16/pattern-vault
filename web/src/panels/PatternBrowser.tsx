import { useState } from 'react'
import { GlassPanel } from '@/components/GlassPanel'
import { SearchBar } from '@/components/SearchBar'
import { FilterChips } from '@/components/FilterChips'
import { PatternCard } from '@/components/PatternCard'
import { usePatterns, useSearchPatterns, useCategories } from '@/api/hooks/usePatterns'
import { useUIStore } from '@/stores/uiStore'

export function PatternBrowser() {
  const [query, setQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const selectedPatternId = useUIStore((s) => s.selectedPatternId)
  const selectPattern = useUIStore((s) => s.selectPattern)

  const { data: categories = [] } = useCategories()
  const { data: allPatterns = [], isLoading: loadingAll } = usePatterns()
  const { data: searchResults, isLoading: loadingSearch } = useSearchPatterns(
    query,
    { category: categoryFilter ?? undefined }
  )

  const patterns = query ? (searchResults ?? []) : allPatterns
  const filtered = categoryFilter && !query
    ? patterns.filter((p) => p.category === categoryFilter)
    : patterns
  const loading = query ? loadingSearch : loadingAll

  return (
    <GlassPanel className="flex-1 flex flex-col">
      <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant/20">
        <span className="font-mono text-label-caps text-on-surface-variant uppercase tracking-tighter">
          Patterns
        </span>
        <span className="font-mono text-[10px] text-outline">
          {filtered.length} result{filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="p-3 space-y-3 border-b border-outline-variant/10">
        <SearchBar value={query} onChange={setQuery} />
        <FilterChips
          items={categories}
          selected={categoryFilter}
          onSelect={setCategoryFilter}
        />
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="text-center py-8 space-y-2">
            <span className="material-symbols-outlined text-[36px] text-outline/50">search_off</span>
            <p className="text-on-surface-variant text-sm">
              {query ? `No patterns match "${query}"` : 'No patterns indexed yet'}
            </p>
            <p className="text-outline text-[11px]">
              Scan a repository to populate the vault
            </p>
          </div>
        )}

        {filtered.map((pattern) => (
          <PatternCard
            key={pattern.id}
            pattern={pattern}
            selected={pattern.id === selectedPatternId}
            onClick={() => selectPattern(pattern.id)}
          />
        ))}
      </div>
    </GlassPanel>
  )
}
