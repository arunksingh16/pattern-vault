import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'

export function useSessions() {
  return useQuery({
    queryKey: ['history'],
    queryFn: () => api.history.list(),
  })
}

export function useSessionMessages(sessionId: number | null) {
  return useQuery({
    queryKey: ['history', sessionId],
    queryFn: () => api.history.get(sessionId!),
    enabled: !!sessionId,
  })
}

export function useDeleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.history.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['history'] }),
  })
}
