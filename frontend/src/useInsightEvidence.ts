import { useCallback, useEffect, useRef, useState } from 'react'
import type { InsightEvidence } from './generated/InsightEvidence'

export function useInsightEvidence(matchId: string | null) {
  const [data, setData] = useState<InsightEvidence | null>(null)
  const [requestedId, setRequestedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const request = useRef<AbortController | null>(null)

  useEffect(() => () => request.current?.abort(), [matchId])

  const close = useCallback(() => {
    request.current?.abort()
    setData(null); setRequestedId(null); setLoading(false); setError(null)
  }, [])

  const open = useCallback(async (insightId: string): Promise<InsightEvidence | null> => {
    if (!matchId) return null
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setRequestedId(insightId); setLoading(true); setError(null); setData(null)
    try {
      const response = await fetch(`/api/matches/${encodeURIComponent(matchId)}/insights/${encodeURIComponent(insightId)}/evidence`, { signal: controller.signal })
      if (!response.ok) {
        const result = await response.json() as { detail?: string }
        throw new Error(result.detail ?? 'Could not load the saved evidence. Try again.')
      }
      const result = await response.json() as InsightEvidence
      if (controller.signal.aborted) return null
      setData(result)
      return result
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load saved evidence.')
      return null
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [matchId])

  return { data, requestedId, loading, error, open, close }
}
