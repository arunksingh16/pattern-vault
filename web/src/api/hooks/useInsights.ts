import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'

export function useInsights() {
  return useQuery({
    queryKey: ['insights'],
    queryFn: () => api.insights.list(),
  })
}

export function useCreateInsight() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { repo_path: string; insight_text: string; tags?: string[] }) =>
      api.insights.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['insights'] }),
  })
}

export function useDeleteInsight() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.insights.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['insights'] }),
  })
}
