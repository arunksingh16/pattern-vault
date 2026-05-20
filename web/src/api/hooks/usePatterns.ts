import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Pattern } from '@/api/client'

export function usePatterns(limit = 25) {
  return useQuery({
    queryKey: ['patterns', limit],
    queryFn: () => api.patterns.list(limit),
  })
}

export function usePattern(id: number | null) {
  return useQuery({
    queryKey: ['pattern', id],
    queryFn: () => api.patterns.get(id!),
    enabled: id !== null,
  })
}

export function useSearchPatterns(query: string, opts?: { category?: string; language?: string }) {
  return useQuery({
    queryKey: ['patterns', 'search', query, opts],
    queryFn: () => api.patterns.search(query, opts),
    enabled: query.length > 0,
  })
}

export function useDeletePattern() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.patterns.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['patterns'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
  })
}

export function useUpdatePattern() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Pattern> & { code_text?: string } }) =>
      api.patterns.update(id, data),
    onSuccess: (_result, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['pattern', id] })
      queryClient.invalidateQueries({ queryKey: ['patterns'] })
    },
  })
}

export function useVaultStats() {
  return useQuery({ queryKey: ['stats'], queryFn: api.stats })
}

export function useCategories() {
  return useQuery({ queryKey: ['categories'], queryFn: api.categories })
}

export function useTags(category?: string) {
  return useQuery({
    queryKey: ['tags', category],
    queryFn: () => api.tags(category),
  })
}

export type { Pattern }
