import { useMemo, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { HowItWorks, Kpis, Meter, PageHead, Pill, RatingBadge, Section, Sql, TableScroll, Loading } from '../components/ui'
import type { CommitmentView } from '../data/api'
import type { EsgRow } from '../data/engine'
import { usePortal } from '../data/portal'
import { useExchange, useQuery } from '../data/store'
import { shortCompany } from '../lib/bands'
import { inrCompact, monthLabel, num, shortNum } from '../lib/format'
import type { ImpactReport } from '../data/types'
import { promisedChange } from '../lib/claim'
import { metricLabel, sectorLabel, unitShort } from '../lib/labels'
import { expectedByNow, latestReport, progressSoFar, shareOfPromise } from '../lib/progress'

const WINDOW_SQL = `SUM(month_impact) OVER (PARTITION BY company_id ORDER BY month
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)    AS cumulative_impact,
month_impact - LAG(month_impact) OVER w_ordered              AS mom_delta,
AVG(month_impact) OVER (PARTITION BY company_id ORDER BY month
      ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)              AS rolling_3mo_esg,
PERCENT_RANK() OVER (PARTITION BY month
      ORDER BY month_impact)                                  AS peer_percentile,

-- ngo_leaderboard
DENSE_RANK() OVER (PARTITION BY sector
      ORDER BY total_impact / total_funded DESC)              AS sector_rank`

export function Impact() {
  const { companyId } = useExchange()
  const { to } = usePortal()
  const { data: companies } = useQuery(api => api.companies())
  const { data: timeline } = useQuery(api => api.esgTimeline())
  const { data: leaders } = useQuery(api => api.leaderboard())
  const { data: commitments } = useQuery(api => api.commitments())
  const { data: reports } = useQuery(api => api.impactReports())

  const company = companies?.find(c => c.id === companyId)
  const rows = useMemo(() => (timeline ?? []).filter(r => r.companyId === companyId), [timeline, companyId])

  const [picked, setPicked] = useState<string | null>(null)
  const active = rows.find(r => r.month === picked) ?? rows.at(-1)

  if (!company || !timeline || !leaders) return <Loading page="Impact">Loading impact</Loading>
  const name = shortCompany(company.name)

  const funded = (commitments ?? []).filter(c => c.commitment.companyId === companyId && c.commitment.status !== 'cancelled')
  const sorted = [...(leaders ?? [])].sort((a, b) => a.sector.localeCompare(b.sector) || a.sectorRank - b.sectorRank)

  return (
    <>
      <PageHead title="Impact" lead="Progress your funded projects report each month. Pick a month to see its figures." />

      {rows.length > 0 && (
        <Kpis items={[
          { label: 'Projects reporting', value: rows.at(-1)!.activeProjects },
          { label: 'Gains reported, all projects', value: num(rows.at(-1)!.cumulativeImpact, 1) },
          { label: '3-month average', value: num(rows.at(-1)!.rolling3mo, 2) },
          { label: 'Months reported', value: rows.length },
        ]} />
      )}

      {funded.length > 0 && reports && (
        <Section id="targets" title="Progress against targets"
          hint="Each project's monthly gains added up, against the bar and what its proposal promised">
          <TableScroll label="Progress against targets">
            <table className="table register">
              <thead>
                <tr>
                  <th scope="col">Project</th><th scope="col" className="r">Promised</th>
                  <th scope="col" className="r">Expected by now</th><th scope="col" className="r">Reported so far</th>
                  <th scope="col">Share of the promise</th><th scope="col">Latest rating</th>
                </tr>
              </thead>
              <tbody>{funded.map(v => <TargetRow key={v.commitment.id} v={v} reports={reports} />)}</tbody>
            </table>
          </TableScroll>
        </Section>
      )}

      {rows.length === 0 ? (
        <div className="empty">
          <h3>No progress reported yet</h3>
          <p>Impact appears once a project you fund files its first monthly report.</p>
          <Link to={to('/find')} className="btn btn--turmeric">Find a project to fund</Link>
        </div>
      ) : (
        <div className="impact">
          <div className="impact__chart">
            <EsgChart rows={rows} activeMonth={active!.month} onPick={setPicked} />
            <ul className="legend">
              <li><span className="swatch weave" data-tone="released" aria-hidden="true" /><span>Progress reported that month</span></li>
              <li><span className="swatch swatch--line" aria-hidden="true" /><span>3-month average</span></li>
            </ul>
          </div>

          <div className="impact__readout" aria-live="polite">
            <h2 className="readout__month display">{monthLabel(active!.month)}</h2>
            <Readout row={active!} name={name} />
          </div>
        </div>
      )}

      <Section id="leaders" title="NGO leaderboard" hint="Impact reported for each ₹10 lakh funded, ranked within each sector">
        <TableScroll label="NGO leaderboard rows">
        <table className="table register leaders">
          <thead>
            <tr>
              <th scope="col">NGO</th><th scope="col">Sector</th><th scope="col" className="r">Projects</th>
              <th scope="col" className="r">Funded</th><th scope="col" className="r">Impact per ₹10 lakh</th><th scope="col" className="r">Rank in sector</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(l => (
              <tr key={l.ngoId} data-funded={l.totalFunded > 0 || undefined}>
                <th scope="row">{l.ngoName}</th>
                <td>{sectorLabel(l.sector)}</td>
                <td className="r num">{l.projectCount}</td>
                <td className="r num">{l.totalFunded > 0 ? inrCompact(l.totalFunded) : <span className="faint">Not funded</span>}</td>
                <td className="r num">{l.impactPerMillion != null ? <strong>{num(l.impactPerMillion, 2)}</strong> : <span className="faint">None yet</span>}</td>
                <td className="r">{l.totalFunded > 0 ? <Pill tone={l.sectorRank === 1 ? 'indigo' : 'linen'}>{ordinal(l.sectorRank)}</Pill> : <span className="faint">Not ranked</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </TableScroll>
      </Section>

      <HowItWorks>
        <p>
          Every figure on this page is computed inside Postgres by window functions over the NGOs' monthly reports,
          each time the page loads. Nothing is stored or calculated in the app.
        </p>
        <Sql label="db/migrations/005_views_windows.sql">{WINDOW_SQL}</Sql>
      </HowItWorks>
    </>
  )
}

/** One funded project: its reported gains against the change its proposal promised. */
function TargetRow({ v, reports }: { v: CommitmentView; reports: ImpactReport[] }) {
  const { to } = usePortal()
  const { data: d } = useQuery(api => api.projectDetail(v.project.id), [v.project.id])
  const target = d?.extraction?.targetMetric ?? null
  const ip = d?.prediction ?? null
  const unit = target?.unit ?? ip?.metricUnit
  const name = target?.name ?? ip?.metricName
  const measured = !!unit && unit !== 'normalised_0_1'
  const promised = measured ? promisedChange(target) : null
  const { total, months } = progressSoFar(reports, v.project.id)
  const share = shareOfPromise(total, promised)
  const bar = expectedByNow(promised, months, v.project.durationMonths)
  const latest = latestReport(reports, v.project.id)
  const u = measured ? ` ${unitShort(unit!)}` : ''
  return (
    <tr>
      <th scope="row">
        <Link to={to(`/projects/${v.project.id}`)} className="register__title">{v.project.title}</Link>
        <span className="faint small">{v.ngoName}{d ? `, ${measured && name ? metricLabel(name) : 'no measurable target'}` : ''}</span>
      </th>
      <td className="r num">{promised != null ? `+${shortNum(promised)}${u}` : <span className="faint">None stated</span>}</td>
      <td className="r num">{bar != null && months > 0 ? `+${shortNum(bar)}${u}` : <span className="faint">None yet</span>}</td>
      <td className="r num">{months ? `+${shortNum(total)}${u}` : <span className="faint">None yet</span>}
        {months > 0 && <span className="faint small block">{months} month{months === 1 ? '' : 's'}</span>}</td>
      <td>
        {share != null && months > 0 ? (
          <div className="share">
            <Meter value={Math.min(1, share)} tone={share >= 1 ? 'neem' : 'indigo'} label={`${v.project.title}: share of the promised gain`} />
            <span className="num small">{Math.round(share * 100)}%</span>
          </div>
        ) : <span className="faint">Not measurable yet</span>}
      </td>
      <td>
        {latest ? <RatingBadge rating={latest.rating} /> : <span className="faint">No reports</span>}
        {latest?.ratingReason && <span className="faint small block">{latest.ratingReason}</span>}
      </td>
    </tr>
  )
}

function ordinal(n: number): string {
  const suffix = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (suffix[(v - 20) % 10] || suffix[v] || suffix[0])
}

// ---------------------------------------------------------------- readout

function Readout({ row, name }: { row: EsgRow; name: string }) {
  const signed = (n: number) => `${n >= 0 ? '+' : ''}${num(n, 2)}`
  return (
    <dl className="readout">
      <div>
        <dt>Reported this month</dt>
        <dd className="num">{num(row.monthImpact, 2)}</dd>
      </div>
      <div>
        <dt>Change from last month</dt>
        <dd className="num">{row.momDelta === null ? 'First month' : signed(row.momDelta)}</dd>
      </div>
      <div>
        <dt>3-month average</dt>
        <dd className="num">{num(row.rolling3mo, 2)}</dd>
      </div>
      <div>
        <dt>Running total</dt>
        <dd className="num">{num(row.cumulativeImpact, 2)}</dd>
      </div>
      <div>
        <dt>Standing among companies</dt>
        <dd className={row.peersInMonth > 1 ? 'num' : 'readout__text'}>
          {row.peersInMonth > 1 ? `${ordinal(Math.round(row.peerPercentile * 100))} percentile` : 'Nobody to compare'}
        </dd>
        {row.peersInMonth <= 1 && <dd className="faint small">Only {name} reported this month.</dd>}
      </div>
    </dl>
  )
}

// ---------------------------------------------------------------- chart

const W = 760, H = 400
const M = { l: 46, r: 20, t: 26, b: 52 }

function niceMax(v: number): number {
  const steps = [1, 2, 4, 5, 8, 10, 20, 40, 50, 80, 100]
  return steps.find(s => s >= v * 1.08) ?? Math.ceil(v * 1.1)
}

function EsgChart({ rows, activeMonth, onPick }: { rows: EsgRow[]; activeMonth: string; onPick: (m: string) => void }) {
  const plotW = W - M.l - M.r
  const plotH = H - M.t - M.b
  const yMax = niceMax(Math.max(...rows.map(r => Math.max(r.monthImpact, r.rolling3mo))))
  const band = plotW / rows.length
  const barW = Math.min(64, band * 0.58)
  const x = (i: number) => M.l + band * i + band / 2
  const y = (v: number) => M.t + plotH - (v / yMax) * plotH
  const ticks = [0, 1, 2, 3, 4].map(i => (yMax / 4) * i)

  const onKey = (e: KeyboardEvent, i: number) => {
    if (e.key === 'ArrowRight' && i < rows.length - 1) onPick(rows[i + 1].month)
    if (e.key === 'ArrowLeft' && i > 0) onPick(rows[i - 1].month)
  }

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Progress reported each month with its 3-month average">
      <defs>
        <pattern id="dye" width="4" height="3" patternUnits="userSpaceOnUse">
          <rect width="4" height="3" fill="#5566c4" />
          <path d="M0 0.5h4" stroke="rgba(0,0,0,.22)" strokeWidth="1" />
          <path d="M0.5 0v3" stroke="rgba(255,255,255,.18)" strokeWidth="1" />
        </pattern>
        <pattern id="dye-active" width="4" height="3" patternUnits="userSpaceOnUse">
          <rect width="4" height="3" fill="#2c3a8c" />
          <path d="M0 0.5h4" stroke="rgba(0,0,0,.3)" strokeWidth="1" />
          <path d="M0.5 0v3" stroke="rgba(255,255,255,.16)" strokeWidth="1" />
        </pattern>
      </defs>

      {ticks.map(t => (
        <g key={t}>
          <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke="rgba(27,35,88,.13)" strokeDasharray={t === 0 ? undefined : '2 5'} />
          <text x={M.l - 10} y={y(t) + 4} textAnchor="end" className="chart__tick">{Number.isInteger(t) ? t : t.toFixed(1)}</text>
        </g>
      ))}

      {rows.map((r, i) => {
        const on = r.month === activeMonth
        const yearStart = i === 0 || r.month.slice(0, 4) !== rows[i - 1].month.slice(0, 4)
        return (
          <g key={r.month}>
          <g tabIndex={0} role="button" aria-pressed={on} className="chart__bar"
            aria-label={`${monthLabel(r.month)}: ${num(r.monthImpact, 2)} reported`}
            onClick={() => onPick(r.month)} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') ? onPick(r.month) : onKey(e, i)}>
            <rect x={x(i) - band / 2} y={M.t} width={band} height={plotH + 28} fill="transparent" />
            <rect x={x(i) - barW / 2} y={y(r.monthImpact)} width={barW} height={y(0) - y(r.monthImpact)} rx="3"
              fill={on ? 'url(#dye-active)' : 'url(#dye)'} />
            {on && <rect x={x(i) - barW / 2 - 3} y={y(r.monthImpact) - 3} width={barW + 6} height={y(0) - y(r.monthImpact) + 3} rx="5"
              fill="none" stroke="#e3a21a" strokeWidth="3" />}
            <text x={x(i)} y={H - M.b + 22} textAnchor="middle" className={`chart__month${on ? ' is-on' : ''}`}>
              {new Date(r.month).toLocaleDateString('en-GB', { month: 'short', timeZone: 'UTC' })}
            </text>
          </g>
          {/* The year is an axis label, so it sits outside the bar's button and its name. */}
          {yearStart && (
            <text x={x(i)} y={H - M.b + 40} textAnchor="middle" className="chart__year" aria-hidden="true">{r.month.slice(0, 4)}</text>
          )}
          </g>
        )
      })}

      <polyline fill="none" stroke="#0f1538" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round"
        points={rows.map((r, i) => `${x(i)},${y(r.rolling3mo)}`).join(' ')} />
      {rows.map((r, i) => (
        <circle key={r.month} cx={x(i)} cy={y(r.rolling3mo)} r={r.month === activeMonth ? 6 : 4.5}
          fill="#e3a21a" stroke="#0f1538" strokeWidth="2" pointerEvents="none" />
      ))}
    </svg>
  )
}
