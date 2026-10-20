import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from 'react'
import type { ActionResult, ExchangeApi } from './api'
import { createDemoApi } from './demoApi'
import type { Effect } from './engine'
import { createHttpApi, probeApi } from './httpApi'

export interface Receipt {
  title: string
  ok: boolean
  /** What the database did, or the error it raised. */
  effects: Effect[]
  error?: string
  kind?: 'sql' | 'rule'
  code?: string
}

/** Where the data comes from: Postgres through the API, or the in-browser copy of its rules. */
export type Source = 'live' | 'demo'

interface Link {
  api: ExchangeApi
  source: Source
  canReset: boolean
}

interface Ctx extends Link {
  /** Bumped after every write so reads refetch. */
  version: number
  companyId: number
  setCompanyId: (id: number) => void
  receipt: Receipt | null
  dismissReceipt: () => void
  /** Run a write, show its receipt, and refresh every read. */
  act: (title: string, run: (api: ExchangeApi) => Promise<ActionResult>) => Promise<ActionResult>
  reset: () => Promise<void>
  /** Set when a request failed to reach the API (not when the database said no). */
  fault: string | null
  reportFault: (err: unknown) => void
  retry: () => void
}

const ExchangeContext = createContext<Ctx | null>(null)

const COMPANY_KEY = 'csr-exchange.company'

function readCompany(): number {
  try {
    const v = Number(localStorage.getItem(COMPANY_KEY))
    return v > 0 ? v : 1
  } catch {
    return 1
  }
}

// ------------------------------------------------------------ choosing the data source

type Boot =
  | { state: 'checking' }
  | { state: 'unreachable' }
  | { state: 'ready'; link: Link }

/** VITE_DATA_SOURCE=demo|live forces one; anything else tries the API and falls back to the demo. */
const PREFERENCE = import.meta.env.VITE_DATA_SOURCE as string | undefined

const demoLink = (): Link => ({ api: createDemoApi(), source: 'demo', canReset: true })

export function ExchangeProvider({ children }: { children: ReactNode }) {
  const [boot, setBoot] = useState<Boot>(() =>
    PREFERENCE === 'demo' ? { state: 'ready', link: demoLink() } : { state: 'checking' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (boot.state === 'ready') return
    let live = true
    setBoot({ state: 'checking' })
    probeApi().then(health => {
      if (!live) return
      if (health) setBoot({ state: 'ready', link: { api: createHttpApi(), source: 'live', canReset: health.resetEnabled } })
      else if (PREFERENCE === 'live') setBoot({ state: 'unreachable' })
      else setBoot({ state: 'ready', link: demoLink() })
    })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])

  if (boot.state === 'checking') {
    return <div className="boot" role="status" aria-busy="true"><p>Connecting to the exchange</p></div>
  }
  if (boot.state === 'unreachable') {
    return (
      <div className="boot" role="alert">
        <h1 className="display">The API is not answering.</h1>
        <p>This build was told to use the database, and nothing replied at /api. Start the API
          (<code>make api</code>) and the database it needs (<code>make up</code>), then try again.</p>
        <button className="btn" onClick={() => setAttempt(a => a + 1)}>Try again</button>
      </div>
    )
  }
  return <ExchangeSession link={boot.link}>{children}</ExchangeSession>
}

// ------------------------------------------------------------ the session

function ExchangeSession({ link, children }: { link: Link; children: ReactNode }) {
  const { api } = link
  const [version, setVersion] = useState(0)
  const [companyId, setCompanyIdState] = useState(readCompany)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [fault, setFault] = useState<string | null>(null)

  const setCompanyId = useCallback((id: number) => {
    setCompanyIdState(id)
    try { localStorage.setItem(COMPANY_KEY, String(id)) } catch { /* private mode */ }
  }, [])

  const reportFault = useCallback((err: unknown) => {
    setFault(err instanceof Error ? err.message : 'Something went wrong talking to the API.')
  }, [])

  const retry = useCallback(() => {
    setFault(null)
    setVersion(v => v + 1)
  }, [])

  const act = useCallback<Ctx['act']>(async (title, run) => {
    let result: ActionResult
    try {
      result = await run(api)
    } catch (err) {
      reportFault(err)
      return { ok: false, kind: 'rule', error: 'The request did not reach the database.' }
    }
    setReceipt(result.ok
      ? { title, ok: true, effects: result.effects }
      : { title, ok: false, effects: [], error: result.error, kind: result.kind, code: result.code })
    setVersion(v => v + 1)
    return result
  }, [api, reportFault])

  const dismissReceipt = useCallback(() => setReceipt(null), [])

  const reset = useCallback(async () => {
    try {
      await api.reset()
    } catch (err) {
      reportFault(err)
      return
    }
    setReceipt(null)
    setFault(null)
    setVersion(v => v + 1)
  }, [api, reportFault])

  const value = useMemo<Ctx>(() => ({
    ...link, version, companyId, setCompanyId, receipt, dismissReceipt, act, reset, fault, reportFault, retry,
  }), [link, version, companyId, setCompanyId, receipt, dismissReceipt, act, reset, fault, reportFault, retry])

  return <ExchangeContext.Provider value={value}>{children}</ExchangeContext.Provider>
}

export function useExchange(): Ctx {
  const ctx = useContext(ExchangeContext)
  if (!ctx) throw new Error('useExchange must be used inside ExchangeProvider')
  return ctx
}

/**
 * Read from the API; refetches after every write. After a write the previous result
 * stays on screen while the fresh one loads, so the page does not flash empty. If the
 * `deps` change (another project, another company) the old result belongs to something
 * else, so it is dropped and `data` is undefined until the new one arrives.
 */
export function useQuery<T>(read: (api: ExchangeApi) => Promise<T>, deps: unknown[] = []) {
  const { api, version, reportFault } = useExchange()
  const key = JSON.stringify(deps)
  const [result, setResult] = useState<{ key: string; data: T }>()
  const readRef = useRef(read)
  readRef.current = read

  useEffect(() => {
    let live = true
    readRef.current(api).then(
      data => { if (live) setResult({ key, data }) },
      err => { if (live) reportFault(err) },
    )
    return () => { live = false }
  }, [api, version, key, reportFault])

  const fresh = result?.key === key
  return { data: fresh ? result.data : undefined, loading: !fresh }
}
