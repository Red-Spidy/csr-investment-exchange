// ExchangeApi over HTTP: the FastAPI service in api/, which runs everything in
// Postgres. The routes return exactly the shapes api.ts declares, so this file only
// moves JSON. A write the database refuses still arrives as a normal ActionResult
// (ok: false); only a bad request or an unreachable service is thrown.

import type { ExchangeApi } from './api'

const UNREACHABLE = 'The API is not reachable. Check that it is running (make api) and that Postgres is up.'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface Health {
  status: 'ok'
  /** Whether POST /api/reset will rebuild the database (CSR_ALLOW_RESET=1 on the server). */
  resetEnabled: boolean
}

/** Is the API there, and is its database ready? Null means use the in-browser demo. */
export async function probeApi(base = '/api', timeoutMs = 2000): Promise<Health | null> {
  try {
    const res = await fetch(`${base}/health`, { signal: AbortSignal.timeout(timeoutMs) })
    if (!res.ok) return null
    const body = await res.json()
    return body?.status === 'ok' ? (body as Health) : null
  } catch {
    return null
  }
}

export function createHttpApi(base = '/api'): ExchangeApi {
  async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
    let res: Response
    try {
      res = await fetch(`${base}${path}`, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch {
      throw new ApiError(0, UNREACHABLE)
    }
    if (!res.ok) {
      // A dev proxy answers 502/504 with a bare status line when nothing is listening.
      let detail = res.status === 502 || res.status === 504 ? UNREACHABLE : res.statusText || `HTTP ${res.status}`
      try {
        const payload = await res.json()
        if (typeof payload?.detail === 'string') detail = payload.detail
      } catch { /* not JSON */ }
      throw new ApiError(res.status, detail)
    }
    return res.json() as Promise<T>
  }

  const get = <T>(path: string) => request<T>('GET', path)
  const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, body)

  return {
    companies: () => get('/companies'),
    rulebooks: () => get('/rulebooks'),
    scorecard: () => get('/scorecard'),
    projectDetail: id => get(`/projects/${id}`),
    matches: rulebookId => get(`/rulebooks/${rulebookId}/matches`),
    commitments: () => get('/commitments'),
    ledger: () => get('/ledger'),
    audit: () => get('/audit'),
    esgTimeline: () => get('/esg-timeline'),
    leaderboard: () => get('/leaderboard'),

    commitFunds: args => post('/commitments', args),
    submitEvidence: (milestoneId, metric) => post(`/milestones/${milestoneId}/evidence`, { metric }),
    verifyMilestone: milestoneId => post(`/milestones/${milestoneId}/verify`),
    failMilestone: milestoneId => post(`/milestones/${milestoneId}/fail`),
    reportImpact: (projectId, value) => post(`/projects/${projectId}/impact-reports`, { value }),
    tryLedgerMutation: (op, ledgerId) => post(`/ledger/${ledgerId}/attempts`, { op }),
    runRace: guards => post('/safeguards/race', guards),
    reset: async () => { await post('/reset') },
  }
}
