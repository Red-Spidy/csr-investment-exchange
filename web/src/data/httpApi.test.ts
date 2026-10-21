import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createHttpApi, probeApi } from './httpApi'

/** A canned answer. Each call gets a fresh Response, because a body can be read only once. */
const reply = (status: number, body: unknown) => () =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function stubFetch(response: (() => Response) | Error) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response
    return response()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => vi.unstubAllGlobals())

describe('createHttpApi: proposals, rulebooks and review', () => {
  it('posts each to its own route and body', async () => {
    const f = stubFetch(reply(200, { ok: true, effects: [], projectId: 9 }))
    const api = createHttpApi('/api')
    const proposal = { ngoId: 1, title: 'T', proposalText: 'x'.repeat(60), sector: 'education' as const,
      state: 'Bihar', requestedAmount: 900_000, durationMonths: 12, numPhases: 2 }
    const rulebook = { companyId: 1, requirementText: 'Fund girls education', focusAreas: ['education' as const],
      preferredStates: ['Bihar'], targetSdgs: [4, 5], minBudget: 0, maxBudget: 3_000_000 }
    expect(await api.submitProposal(proposal)).toEqual({ ok: true, effects: [], projectId: 9 })
    await api.reviewProject(7, true, 'budget received')
    await api.createRulebook(rulebook)
    const calls = f.mock.calls.map(c => c as unknown as [string, RequestInit])
    expect(calls.map(([url, init]) => [url, init.method, JSON.parse(init.body as string)])).toEqual([
      ['/api/projects', 'POST', proposal],
      ['/api/projects/7/review', 'POST', { approve: true, note: 'budget received' }],
      ['/api/rulebooks', 'POST', rulebook],
    ])
  })
})

describe('createHttpApi', () => {
  it('reads from the route that matches each ExchangeApi method', async () => {
    const f = stubFetch(reply(200, []))
    const api = createHttpApi('/api')
    await api.companies()
    await api.projectDetail(7)
    await api.matches(3)
    await api.esgTimeline()
    expect(f.mock.calls.map(c => (c as unknown[])[0])).toEqual([
      '/api/companies', '/api/projects/7', '/api/rulebooks/3/matches', '/api/esg-timeline',
    ])
  })

  it('posts a commitment as JSON', async () => {
    const f = stubFetch(reply(200, { ok: true, effects: [], commitmentId: 2 }))
    const out = await createHttpApi('/api').commitFunds({ companyId: 2, projectId: 3, amount: 3_200_000 })
    expect(out).toEqual({ ok: true, effects: [], commitmentId: 2 })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/commitments')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ companyId: 2, projectId: 3, amount: 3_200_000 })
  })

  it('hands back a refusal from the database as a result, not an exception', async () => {
    stubFetch(reply(200, { ok: false, kind: 'sql', error: 'project 1 is active, only approved projects can be funded', code: 'P0001' }))
    const out = await createHttpApi('/api').commitFunds({ companyId: 1, projectId: 1 })
    expect(out).toMatchObject({ ok: false, kind: 'sql', code: 'P0001' })
  })

  it('maps each write to its own route and body', async () => {
    const f = stubFetch(reply(200, { ok: true, effects: [] }))
    const api = createHttpApi('/api')
    await api.submitEvidence(2, 4.2)
    await api.verifyMilestone(2)
    await api.failMilestone(3)
    await api.terminateCommitment(1, 'Phase 2 failed verification')
    await api.reportImpact(1, 8.2)
    await api.tryLedgerMutation('DELETE', 1)
    const calls = f.mock.calls.map(c => {
      const [url, init] = c as unknown as [string, RequestInit]
      return [url, JSON.parse(init.body as string)]
    })
    expect(calls).toEqual([
      ['/api/milestones/2/evidence', { metric: 4.2 }],
      ['/api/milestones/2/verify', {}],
      ['/api/milestones/3/fail', {}],
      ['/api/commitments/1/terminate', { reason: 'Phase 2 failed verification' }],
      ['/api/projects/1/impact-reports', { value: 8.2 }],
      ['/api/ledger/1/attempts', { op: 'DELETE' }],
    ])
  })

  it('throws an ApiError with the server detail on a non-2xx answer', async () => {
    stubFetch(reply(404, { detail: 'project 999 not found' }))
    await expect(createHttpApi('/api').projectDetail(999)).rejects.toMatchObject({
      name: 'ApiError', status: 404, message: 'project 999 not found',
    })
  })

  it('turns a bare proxy 502 into a message that says what to do', async () => {
    stubFetch(() => new Response('', { status: 502, statusText: 'Bad Gateway' }))
    const err = await createHttpApi('/api').companies().catch(e => e)
    expect(err.status).toBe(502)
    expect(err.message).toContain('make api')
  })

  it('throws an ApiError with status 0 when the API cannot be reached', async () => {
    stubFetch(new TypeError('Failed to fetch'))
    const err = await createHttpApi('/api').companies().catch(e => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(0)
  })
})

describe('probeApi', () => {
  it('returns the health payload when the API and its database are up', async () => {
    stubFetch(reply(200, { status: 'ok', resetEnabled: true }))
    expect(await probeApi('/api')).toEqual({ status: 'ok', resetEnabled: true })
  })

  it('returns null when the database is not ready (503)', async () => {
    stubFetch(reply(503, { detail: 'database unavailable' }))
    expect(await probeApi('/api')).toBeNull()
  })

  it('returns null when nothing answers', async () => {
    stubFetch(new TypeError('Failed to fetch'))
    expect(await probeApi('/api')).toBeNull()
  })
})
