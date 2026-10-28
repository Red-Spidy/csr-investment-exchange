import type { ReactNode } from 'react'
import type { ProjectStatus } from '../data/types'
import { fixed } from '../lib/format'
import { STATUS_LABEL } from '../lib/labels'

// ---------------------------------------------------------------- page chrome

/** Page title, one line of context, and the page's main actions on the right. */
export function PageHead({ title, lead, children }: { title: ReactNode; lead?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div className="page-head__text">
        <h1>{title}</h1>
        {lead && <p className="page-head__sub">{lead}</p>}
      </div>
      {children && <div className="page-head__actions">{children}</div>}
    </header>
  )
}

/** Headline figures for a page: label above, value below. */
export function Kpis({ items }: { items: { label: string; value: ReactNode; note?: ReactNode; tone?: 'madder' | 'neem' | 'turmeric' }[] }) {
  return (
    <dl className="kpis">
      {items.map(k => (
        <div key={k.label} className="kpi" data-tone={k.tone}>
          <dt>{k.label}</dt>
          <dd className="kpi__value num">{k.value}</dd>
          {k.note && <dd className="kpi__note">{k.note}</dd>}
        </div>
      ))}
    </dl>
  )
}

/** Formulas, SQL and model details, folded away until someone asks. */
export function HowItWorks({ title = 'How this works', children }: { title?: string; children: ReactNode }) {
  return (
    <details className="how">
      <summary>{title}</summary>
      <div className="how__body">{children}</div>
    </details>
  )
}

export function Section({ title, hint, children, id }: {
  title: ReactNode; hint?: ReactNode; children: ReactNode; id?: string
}) {
  return (
    <section className="section" aria-labelledby={id}>
      <div className="section__head">
        <h2 id={id}>{title}</h2>
        {hint && <p className="muted section__hint">{hint}</p>}
      </div>
      {children}
    </section>
  )
}

// ---------------------------------------------------------------- marks

const STATUS_TONE: Record<ProjectStatus, string> = {
  approved: 'neem', flagged: 'madder', active: 'indigo', matched: 'turmeric',
  closed: 'linen', pending: 'linen', scoring: 'linen', rejected: 'madder', terminated: 'madder',
}

/** Wide tables scroll sideways on a phone; the wrapper makes that reachable by keyboard. */
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>{children}</div>
}

/**
 * What a page shows while its data loads or if it never arrives. Pass `page` to keep
 * the page's heading in the document; leave it out where a parent already has one.
 */
export function Loading({ page, children }: { page?: string; children: ReactNode }) {
  return (
    <div className="loading" aria-busy="true">
      {page && <h1 className="sr-only">{page}</h1>}
      {children}
    </div>
  )
}

/** `held`: the project is funded and a milestone failed. The database flags it; to people it is a held payment. */
export function StatusPill({ status, held }: { status: ProjectStatus; held?: boolean }) {
  if (held && status === 'flagged') return <span className="pill" data-tone="madder">Payment held</span>
  return <span className="pill" data-tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</span>
}

export function Pill({ tone, children }: { tone: 'neem' | 'madder' | 'indigo' | 'turmeric' | 'linen'; children: ReactNode }) {
  return <span className="pill" data-tone={tone}>{children}</span>
}

export function Grade({ grade, large }: { grade: string | null; large?: boolean }) {
  if (!grade) return <span className="faint">Not scored</span>
  return (
    <span className={`grade${large ? ' grade--lg' : ''}`} data-grade={grade} aria-label={`Grade ${grade}`}>
      {grade}
    </span>
  )
}

// ---------------------------------------------------------------- measures

/** A 0 to 1 value as a bar. `tone` picks the dye. */
export function Meter({ value, tone = 'indigo', label }: {
  value: number; tone?: 'indigo' | 'madder' | 'neem' | 'turmeric'; label: string
}) {
  const w = Math.max(0, Math.min(1, value)) * 100
  return (
    <div className="meter" data-tone={tone} role="meter" aria-label={label}
      aria-valuemin={0} aria-valuemax={1} aria-valuenow={value}>
      <div className="meter__fill" style={{ width: `${w}%` }} />
    </div>
  )
}

/**
 * The model's expected result with its 10th to 90th percentile range, and the
 * result the NGO's proposal promised. Everything shares one axis.
 */
export function RangeBar({ low, value, high, target, unit, targetLabel = 'Proposal promises' }: {
  low: number; value: number; high: number; target?: number | null; unit: string; targetLabel?: string
}) {
  const min = Math.min(0, low)
  const max = Math.max(high, target ?? 0) * 1.08
  const at = (v: number) => `${((v - min) / (max - min)) * 100}%`
  const fmt = (v: number) => String(Math.round(v * 100) / 100)
  return (
    <div className="range">
      {target != null && (
        <div className="range__target-label" style={{ left: at(target) }}
          data-side={(target - min) / (max - min) > 0.5 ? 'left' : 'right'}>
          {targetLabel} {fmt(target)}
        </div>
      )}
      <div className="range__track">
        <div className="range__span" style={{ left: at(low), width: `calc(${at(high)} - ${at(low)})` }} />
        {target != null && <div className="range__target" style={{ left: at(target) }} />}
        <div className="range__dot" style={{ left: at(value) }} />
      </div>
      <div className="range__ticks" aria-hidden="true">
        <span style={{ left: at(low) }}>{fmt(low)}</span>
        <span className="range__ticks-main" style={{ left: at(value) }}>{fmt(value)}</span>
        <span style={{ left: at(high) }}>{fmt(high)}</span>
      </div>
      <p className="sr-only">
        Expected {fmt(value)} {unit}, likely between {fmt(low)} and {fmt(high)}.
        {target != null && ` The proposal promises ${fmt(target)}.`}
      </p>
    </div>
  )
}

export interface Segment { key: string; label: string; value: number; tone: 'indigo' | 'turmeric' | 'neem' | 'madder' | 'linen'; note?: string }

/** Contributions that add up to a score, drawn as one bar of dyed segments. */
export function ScoreStack({ segments, total, caption }: { segments: Segment[]; total: number; caption: string }) {
  return (
    <div className="stack">
      <div className="stack__bar" role="img" aria-label={caption}>
        {segments.map(s => (
          <div key={s.key} className="stack__seg" data-tone={s.tone}
            style={{ width: `${Math.max(0, s.value) * 100}%` }} title={`${s.label}: ${fixed(s.value, 3)}`} />
        ))}
        <div className="stack__rest" style={{ width: `${Math.max(0, 1 - total) * 100}%` }} />
      </div>
      <ul className="stack__legend">
        {segments.map(s => (
          <li key={s.key}>
            <span className="stack__dot" data-tone={s.tone} aria-hidden="true" />
            <span>{s.label}</span>
            <strong className="num">{fixed(s.value, 3)}</strong>
            {s.note && <span className="faint small">{s.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------- progress ratings

const RATING_TONE: Record<number, 'neem' | 'turmeric' | 'madder'> = { 5: 'neem', 4: 'neem', 3: 'turmeric', 2: 'madder', 1: 'madder' }

/** A rater's 1 (low) to 5 (good). Advice for the reviewer: it never releases money. */
export function RatingBadge({ rating }: { rating: number | null }) {
  if (rating == null) return <span className="pill rating" data-tone="linen">Not rated</span>
  return (
    <span className="pill rating" data-tone={RATING_TONE[rating]} aria-label={`Rated ${rating} of 5`}>
      <span className="pips" aria-hidden="true">
        {[1, 2, 3, 4, 5].map(i => <i key={i} data-on={i <= rating || undefined} />)}
      </span>
      {rating} of 5
    </span>
  )
}

/** "gemini:gemini-2.5-flash" -> "Gemini (gemini-2.5-flash)"; the rules say so. */
export function raterName(ratedBy: string | null): string {
  if (!ratedBy) return ''
  if (ratedBy.startsWith('rules')) return 'the rules (no AI model)'
  const [provider, model] = ratedBy.split(':')
  return `${provider.charAt(0).toUpperCase()}${provider.slice(1)}${model ? ` (${model})` : ''}`
}

interface Rated {
  updateText: string | null
  rating: number | null
  ratingReason: string | null
  ratingFlags: string[]
  ratedBy: string | null
}

/** What the NGO said, and how it was rated: what a reviewer reads before deciding. */
export function Assessment({ item, title = "In the NGO's words" }: { item: Rated; title?: string }) {
  if (!item.updateText && item.rating == null) return null
  return (
    <div className="assessment">
      {item.updateText && (
        <figure className="assessment__words">
          <figcaption>{title}</figcaption>
          <blockquote>{item.updateText}</blockquote>
        </figure>
      )}
      <div className="assessment__rating">
        <RatingBadge rating={item.rating} />
        <span className="small">{item.rating == null ? 'Not rated yet.' : item.ratingReason}</span>
      </div>
      {item.ratingFlags.length > 0 && (
        <ul className="assessment__flags small">{item.ratingFlags.map(f => <li key={f}>{f}</li>)}</ul>
      )}
      {item.ratedBy && <p className="faint small">Rated by {raterName(item.ratedBy)}. A person still decides.</p>}
    </div>
  )
}

/** Progress so far against the promise, with a marker where the bar is. */
export function BarMeter({ value, max, bar, label }: { value: number; max: number; bar: number | null; label: string }) {
  const at = (v: number) => `${Math.max(0, Math.min(1, v / max)) * 100}%`
  return (
    <div className="barmeter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <div className="barmeter__fill" style={{ width: at(value) }} />
      {bar != null && <div className="barmeter__bar" style={{ left: at(bar) }} title="Expected by now" />}
    </div>
  )
}

// ---------------------------------------------------------------- code

export function Sql({ children, label }: { children: string; label?: string }) {
  return (
    <figure className="sql">
      {label && <figcaption>{label}</figcaption>}
      <pre><code>{children}</code></pre>
    </figure>
  )
}
