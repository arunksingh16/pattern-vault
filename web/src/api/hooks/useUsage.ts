import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

export function useDailyUsage(days = 14) {
  return useQuery({
    queryKey: ['usage', 'daily', days],
    queryFn: () => api.usageDaily(days),
  })
}
