import { useEffect } from 'react'
import { usePortal } from '../data/portal'
import { useExchange } from '../data/store'

/**
 * After every write: what the database did, in the database's own words.
 * On failure it shows the exact error Postgres would raise.
 */
export function Receipt() {
  const { receipt, dismissReceipt } = useExchange()
  // NGOs and companies get the outcome in plain words; the review console also sees which part of the database acted.
  const technical = usePortal().role === 'review'

  useEffect(() => {
    if (!receipt) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') dismissReceipt() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [receipt, dismissReceipt])

  if (!receipt) return null

  return (
    <aside className="receipt" data-ok={receipt.ok} aria-live="polite" aria-label="Result">
      <header className="receipt__head">
        <div className="receipt__title">
          <h3>{receipt.title}</h3>
          <span className="pill" data-tone={receipt.ok ? 'neem' : 'madder'}>
            {receipt.ok ? 'Done' : receipt.kind === 'sql' ? 'Database refused' : 'Not allowed'}
          </span>
        </div>
        <button className="receipt__close" onClick={dismissReceipt} aria-label="Dismiss">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </button>
      </header>

      {receipt.ok ? (
        <ol className="receipt__list">
          {receipt.effects.map((e, i) => (
            <li key={i}>
              {technical && <span className="receipt__by">{e.by}</span>}
              <span>{e.text}</span>
            </li>
          ))}
        </ol>
      ) : (
        <div className="receipt__error">
          <p className={technical ? 'code' : undefined}>{technical ? `ERROR: ${receipt.error}` : receipt.error}</p>
          {receipt.kind === 'sql' && (
            <p className="small">{technical ? 'The whole operation was rolled back. No rows changed.' : 'Nothing was changed.'}</p>
          )}
        </div>
      )}
    </aside>
  )
}
