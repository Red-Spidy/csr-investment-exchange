import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useExchange, useQuery } from '../data/store'
import { Receipt } from './Receipt'

const ICONS = {
  exchange: 'M4 7h16M4 12h10M4 17h16',
  projects: 'M7 3.5h7l4 4V20H7zM14 3.5V8h4',
  matching: 'M9 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM15 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9z',
  funds: 'M4 6h16v4.5H4zM4 13.5h16V18H4z',
  impact: 'M4 4v16h16M7.5 15.5l3.5-4 3 2.5 4.5-6',
  safeguards: 'M12 3l7 3v5.2c0 4.6-2.9 7.7-7 9.8-4.1-2.1-7-5.2-7-9.8V6z',
} as const

function Icon({ d }: { d: string }) {
  return (
    <svg className="nav__icon" viewBox="0 0 24 24" width="20" height="20" fill="none"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  )
}

export function Shell() {
  const { companyId, setCompanyId, reset, dismissReceipt, source, canReset, fault, retry } = useExchange()
  const [confirmingReset, setConfirmingReset] = useState(false)
  const { pathname } = useLocation()
  // A receipt describes the last action; it should not follow you to another page.
  useEffect(() => { dismissReceipt() }, [pathname, dismissReceipt])
  const { data: companies } = useQuery(api => api.companies())
  const { data: rulebooks } = useQuery(api => api.rulebooks())
  const { data: commitments } = useQuery(api => api.commitments())

  const rulebook = rulebooks?.find(r => r.companyId === companyId)
  const { data: report } = useQuery(
    api => (rulebook ? api.matches(rulebook.id) : Promise.resolve(undefined)), [rulebook?.id])

  const awaiting = (commitments ?? []).filter(c => c.commitment.status === 'active')
    .flatMap(c => c.milestones).filter(m => m.verification === 'submitted').length
  const matchCount = report?.ranked.length ?? 0

  const links: { to: string; label: string; icon: keyof typeof ICONS; badge?: number; end?: boolean }[] = [
    { to: '/', label: 'Exchange', icon: 'exchange', end: true },
    { to: '/projects', label: 'Projects', icon: 'projects' },
    { to: '/matching', label: 'Matching', icon: 'matching', badge: matchCount },
    { to: '/funds', label: 'Funds', icon: 'funds', badge: awaiting },
    { to: '/impact', label: 'Impact', icon: 'impact' },
    { to: '/safeguards', label: 'Safeguards', icon: 'safeguards' },
  ]

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>

      <aside className="rail">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="32" height="32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="#e3a21a" />
            <g fill="none" strokeWidth="3.2">
              <path d="M6 10h20" stroke="#0f1538" />
              <path d="M6 16h14" stroke="#0f1538" opacity=".55" />
              <path d="M6 22h20" stroke="#0f1538" />
            </g>
          </svg>
          <span className="brand__name">CSR Exchange</span>
        </div>

        <div className="rail__company field">
          <label htmlFor="company">Company</label>
          <select id="company" className="select" value={companyId}
            onChange={e => setCompanyId(Number(e.target.value))}>
            {(companies ?? []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>

        <nav className="nav" aria-label="Main">
          {links.map(l => (
            <NavLink key={l.to} to={l.to} end={l.end} className="nav__link">
              <Icon d={ICONS[l.icon]} />
              <span>{l.label}</span>
              {!!l.badge && <span className="nav__badge" aria-label={`${l.badge} waiting`}>{l.badge}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="rail__foot">
          {source === 'live' ? (
            <div className="demo-chip demo-chip--live">
              <span className="demo-chip__dot" aria-hidden="true" />
              <div>
                <strong>Live database</strong>
                <p>Every number comes from Postgres, through the API.</p>
              </div>
            </div>
          ) : (
            <div className="demo-chip">
              <span className="demo-chip__dot" aria-hidden="true" />
              <div>
                <strong>Demo data</strong>
                <p>Rules from db/migrations, run in your browser. Nothing is saved.</p>
              </div>
            </div>
          )}
          {canReset && (source === 'demo' || !confirmingReset) && (
            <button className="rail__reset" onClick={() => (source === 'demo' ? reset() : setConfirmingReset(true))}>
              {source === 'demo' ? 'Reset demo' : 'Reset database'}
            </button>
          )}
          {canReset && source === 'live' && confirmingReset && (
            <div className="rail__confirm" role="group" aria-label="Confirm database reset">
              <p>Wipe every table and reload the demo scenario?</p>
              <div>
                <button className="rail__reset rail__reset--danger"
                  onClick={() => { setConfirmingReset(false); void reset() }}>Yes, reset</button>
                <button className="rail__reset" onClick={() => setConfirmingReset(false)}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      </aside>

      <main className="main" id="main" tabIndex={-1}>
        {fault && (
          <div className="fault" role="alert">
            <p><strong>Lost contact with the API.</strong> {fault}</p>
            <button className="btn btn--small" onClick={retry}>Try again</button>
          </div>
        )}
        <Outlet />
      </main>

      <Receipt />
    </div>
  )
}
