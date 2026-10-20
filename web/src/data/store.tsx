import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from 'react'
import type { ActionResult, ExchangeApi } from './api'
import { createDemoApi } from './demoApi'
import type { Effect } from './engine'

export interface Receipt {
  title: string
  ok: boolean
  /** What the database did, or the error it raised. */
  effects: Effect[]
  error?: string
  kind?: 'sql' | 'rule'
  code?: string
}

interface Ctx {
  api: ExchangeApi
  /** Bumped after every write so reads refetch. */
  version: number
  companyId: number
  setCompanyId: (id: number) => void
  receipt: Receipt | null
  dismissReceipt: () => void
  /** Run a write, show its receipt, and refresh every read. */
  act: (title: string, run: (api: ExchangeApi) => Promise<ActionResult>) => Promise<ActionResult>
  reset: () => Promise<void>
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

export function ExchangeProvider({ children }: { children: ReactNode }) {
  const api = useMemo(() => createDemoApi(), [])
  const [version, setVersion] = useState(0)
  const [companyId, setCompanyIdState] = useState(readCompany)
  const [receipt, setReceipt] = useState<Receipt | null>(null)

  const setCompanyId = useCallback((id: number) => {
    setCompanyIdState(id)
    try { localStorage.setItem(COMPANY_KEY, String(id)) } catch { /* private mode */ }
  }, [])

  const act = useCallback<Ctx['act']>(async (title, run) => {
    const result = await run(api)
    setReceipt(result.ok
      ? { title, ok: true, effects: result.effects }
      : { title, ok: false, effects: [], error: result.error, kind: result.kind, code: result.code })
    setVersion(v => v + 1)
    return result
  }, [api])

  const dismissReceipt = useCallback(() => setReceipt(null), [])

  const reset = useCallback(async () => {
    await api.reset()
    setReceipt(null)
    setVersion(v => v + 1)
  }, [api])

  const value = useMemo<Ctx>(() => ({
    api, version, companyId, setCompanyId, receipt, dismissReceipt, act, reset,
  }), [api, version, companyId, setCompanyId, receipt, dismissReceipt, act, reset])

  return <ExchangeContext.Provider value={value}>{children}</ExchangeContext.Provider>
}

export function useExchange(): Ctx {
  const ctx = useContext(ExchangeContext)
  if (!ctx) throw new Error('useExchange must be used inside ExchangeProvider')
  return ctx
}

/**
 * Read from the API; refetches after every write. Keeps the previous data
 * on screen while refetching so the page does not flash empty.
 */
export function useQuery<T>(read: (api: ExchangeApi) => Promise<T>, deps: unknown[] = []) {
  const { api, version } = useExchange()
  const [data, setData] = useState<T>()
  const [loading, setLoading] = useState(true)
  const readRef = useRef(read)
  readRef.current = read

  useEffect(() => {
    let live = true
    setLoading(true)
    readRef.current(api).then(d => {
      if (live) { setData(d); setLoading(false) }
    })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, version, ...deps])

  return { data, loading }
}
