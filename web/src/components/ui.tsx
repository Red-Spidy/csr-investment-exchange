import type { ReactNode } from 'react'
import type { ProjectStatus } from '../data/types'
import { fixed } from '../lib/format'
import { STATUS_LABEL } from '../lib/labels'

// ---------------------------------------------------------------- page chrome

export function PageHead({ title, lead, children }: { title: ReactNode; lead?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <h1>{title}</h1>
      {lead && <p className="lead">{lead}</p>}
      {children}
    </header>
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

export function StatusPill({ status }: { status: ProjectStatus }) {
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

// ---------------------------------------------------------------- code

export function Sql({ children, label }: { children: string; label?: string }) {
  return (
    <figure className="sql">
      {label && <figcaption>{label}</figcaption>}
      <pre><code>{children}</code></pre>
    </figure>
  )
}
