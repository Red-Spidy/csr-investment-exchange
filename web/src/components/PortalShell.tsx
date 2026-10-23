import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { PortalProvider, type Portal } from '../data/portal'
import { useExchange } from '../data/store'
import { Receipt } from './Receipt'
import { Loading } from './ui'

const ICONS = {
  home: 'M4 11.5 12 5l8 6.5V20h-5.5v-5h-5v5H4z',
  projects: 'M7 3.5h7l4 4V20H7zM14 3.5V8h4',
  plus: 'M12 5v14M5 12h14',
  find: 'M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM20 20l-4.8-4.8',
  funds: 'M4 6h16v4.5H4zM4 13.5h16V18H4z',
  impact: 'M4 4v16h16M7.5 15.5l3.5-4 3 2.5 4.5-6',
  queue: 'M5 6h14M5 12h14M5 18h9',
  milestones: 'M5 19V5M5 5h11l-2 3.5 2 3.5H5',
  safeguards: 'M12 3l7 3v5.2c0 4.6-2.9 7.7-7 9.8-4.1-2.1-7-5.2-7-9.8V6z',
} as const

export interface NavItem { to: string; label: string; icon: keyof typeof ICONS; badge?: number; end?: boolean }

function Icon({ d }: { d: string }) {
  return (
    <svg className="nav__icon" viewBox="0 0 24 24" width="20" height="20" fill="none"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  )
}

export function Brand() {
  return (
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
  )
}

/**
 * The frame of every portal: who is signed in, where they can go, and the
 * receipt of their last action. The reviewer console alone can rebuild the data.
 */
export function PortalShell({ portal, title, who, links }: {
  portal: Portal
  title: string
  who: ReactNode
  links: NavItem[]
}) {
  const { companyId, setCompanyId, reset, resetting, dismissReceipt, source, canReset, fault, retry } = useExchange()
  const [confirmingReset, setConfirmingReset] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => { dismissReceipt() }, [pathname, dismissReceipt])

  // Company pages read the company from the store; the URL decides which one it is.
  useEffect(() => {
    if (portal.companyId !== null && portal.companyId !== companyId) setCompanyId(portal.companyId)
  }, [portal.companyId, companyId, setCompanyId])
  const ready = portal.companyId === null || portal.companyId === companyId

  return (
    <PortalProvider value={portal}>
      <div className="shell" data-role={portal.role}>
        <a className="skip" href="#main">Skip to content</a>

        <aside className="rail">
          <Brand />
          <div className="rail__who">
            <span className="rail__portal">{title}</span>
            <strong className="rail__name">{who}</strong>
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
            <p className="rail__source" data-live={source === 'live' || undefined}>
              <span className="rail__dot" aria-hidden="true" />
              {source === 'live' ? 'Connected' : 'Offline demo data'}
            </p>
            {portal.role === 'review' && canReset && !confirmingReset && (
              <button className="rail__reset" disabled={resetting} aria-busy={resetting || undefined}
                onClick={() => (source === 'demo' ? reset() : setConfirmingReset(true))}>
                {resetting ? 'Rebuilding…' : 'Reset demo data'}
              </button>
            )}
            {portal.role === 'review' && canReset && confirmingReset && (
              <div className="rail__confirm" role="group" aria-label="Confirm reset">
                <p>Reload the demo scenario and rescore it? Everything since is lost.</p>
                <div>
                  <button className="rail__reset rail__reset--danger"
                    onClick={() => { setConfirmingReset(false); void reset() }}>Reset</button>
                  <button className="rail__reset" onClick={() => setConfirmingReset(false)}>Cancel</button>
                </div>
              </div>
            )}
            <Link className="rail__signout" to="/">Sign out</Link>
          </div>
        </aside>

        <main className="main" id="main" tabIndex={-1}>
          {fault && (
            <div className="fault" role="alert">
              <p><strong>Cannot reach the server.</strong> {fault}</p>
              <button className="btn btn--small" onClick={retry}>Try again</button>
            </div>
          )}
          {ready ? <Outlet /> : <Loading>Opening your account</Loading>}
        </main>

        <Receipt />
      </div>
    </PortalProvider>
  )
}
