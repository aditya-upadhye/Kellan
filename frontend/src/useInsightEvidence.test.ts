import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useInsightEvidence } from './useInsightEvidence'
import { insightFixture } from './test/insightEvidence'

function deferred() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>(done => { resolve = done })
  return { promise, resolve }
}

afterEach(() => vi.unstubAllGlobals())

describe('evidence requests', () => {
  it('ignores an older request that finishes after a different insight is selected', async () => {
    const first = deferred(), second = deferred()
    vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise))
    const { result } = renderHook(() => useInsightEvidence('match-1'))
    let one!: Promise<unknown>, two!: Promise<unknown>
    act(() => { one = result.current.open('first') })
    act(() => { two = result.current.open('second') })
    await act(async () => {
      second.resolve({ ok: true, json: async () => insightFixture('second') } as Response)
      await two
      first.resolve({ ok: true, json: async () => insightFixture('first') } as Response)
      await one
    })
    expect(result.current.data?.insight_id).toBe('second')
    expect(result.current.loading).toBe(false)
  })

  it('keeps the inspector closed when an in-flight request finishes after close', async () => {
    const pending = deferred()
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending.promise))
    const { result } = renderHook(() => useInsightEvidence('match-1'))
    let request!: Promise<unknown>
    act(() => { request = result.current.open('first') })
    act(() => result.current.close())
    await act(async () => {
      pending.resolve({ ok: true, json: async () => insightFixture() } as Response)
      await request
    })
    expect(result.current.data).toBeNull()
    expect(result.current.requestedId).toBeNull()
    expect(result.current.loading).toBe(false)
  })
})
