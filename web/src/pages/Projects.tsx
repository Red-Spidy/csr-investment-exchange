import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Grade, HowItWorks, Meter, PageHead, RangeBar, ScoreStack, Section, StatusPill, TableScroll, Loading } from '../components/ui'
import type { CommitmentView, ProjectDetail } from '../data/api'
import { usePortal } from '../data/portal'
import { useExchange, useQuery } from '../data/store'
import type { SpendingHistory } from '../data/types'
import { CommitmentBlock } from './Funds'
import { promisedChange } from '../lib/claim'
import { inr, inrCompact, num } from '../lib/format'
import { metricLabel, sdgName, sectorLabel, STATUS_LABEL, unitShort } from '../lib/labels'

type Filter = 'all' | 'flagged' | 'approved' | 'funded'
const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'flagged', label: 'In review' },
  { id: 'approved', label: 'Approved' },
  { id: 'funded', label: 'Funded' },
]

/** The review console's project register; with an id, that project's page. */
export function Projects() {
  const { id } = useParams()
  const { to } = usePortal()
  const { data: rows } = useQuery(api => api.scorecard())
  const [filter, setFilter] = useState<Filter>('all')
  if (id) return <ProjectPage />

  const visible = (rows ?? []).filter(r =>
    filter === 'all' ? true
    : filter === 'funded' ? ['matched', 'active', 'closed', 'terminated'].includes(r.status)
    : r.status === filter)
  const count = (f: Filter) => (rows ?? []).filter(r =>
    f === 'all' ? true : f === 'funded' ? ['matched', 'active', 'closed', 'terminated'].includes(r.status) : r.status === f).length

  return (
    <>
      <PageHead title="All projects" lead="Every proposal on the exchange, with the grade the scoring gave it." />

      <div className="filters" role="group" aria-label="Filter projects by status">
        {FILTERS.map(f => (
          <button key={f.id} className="filter" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
            {f.label} <span className="filter__count">{rows ? count(f.id) : ''}</span>
          </button>
        ))}
      </div>

      {!rows ? <Loading>Loading projects</Loading> : visible.length === 0 ? (
        <div className="empty"><h3>No projects here</h3><p>Try another filter.</p></div>
      ) : (
        <TableScroll label="Projects">
          <table className="table register">
            <thead>
              <tr>
                <th scope="col">Project</th><th scope="col">Sector</th><th scope="col" className="r">Requested</th>
                <th scope="col">Grade</th><th scope="col">Status</th><th scope="col" className="r">Funded</th>
              </tr>
            </thead>
            <tbody>
              {visible.map(r => (
                <tr key={r.projectId}>
                  <th scope="row">
                    <Link to={to(`/projects/${r.projectId}`)} className="register__title">{r.title}</Link>
                    <span className="faint small">{r.ngoName}{r.state ? `, ${r.state}` : ''}</span>
                  </th>
                  <td>{sectorLabel(r.sector)}</td>
                  <td className="r num">{inrCompact(r.requestedAmount)}</td>
                  <td><Grade grade={r.grade} /></td>
                  <td><StatusPill status={r.status} /></td>
                  <td className="r num">{r.commitmentId ? inrCompact(r.committedAmount) : <span className="faint">None</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </>
  )
}

/** One project, inside whichever portal opened it. */
export function ProjectPage() {
  const projectId = Number(useParams().id)
  const { to, role } = usePortal()
  const { data: d } = useQuery(api => api.projectDetail(projectId), [projectId])
  const back = role === 'review' ? { to: to('/projects'), label: 'All projects' }
    : role === 'ngo' ? { to: to(), label: 'My projects' }
    : { to: to('/find'), label: 'Find projects' }
  return (
    <>
      <p className="crumb"><Link to={back.to}>{back.label}</Link></p>
      {!d ? <Loading page="Project">Loading project</Loading> : <ProjectView d={d} key={d.project.id} />}
    </>
  )
}

// ---------------------------------------------------------------- detail

const NEXT_STEP: Partial<Record<string, string>> = {
  pending: 'Waiting to be scored.',
  scoring: 'Being scored.',
  approved: 'Companies can now find and fund this project.',
  flagged: 'An exchange reviewer is checking this proposal before it can be funded.',
  rejected: 'The reviewer declined this proposal. It cannot be funded.',
  matched: 'A company has committed funding. Phases open as milestones are verified.',
  active: 'Funded. Each phase is paid once its milestone is verified.',
  closed: 'Every phase has been paid.',
  terminated: 'The company ended its funding early.',
}

function ProjectView({ d }: { d: ProjectDetail }) {
  const { role, companyId, to } = usePortal()
  const { project: p, ngo, extraction: x, prediction: ip, fraud: fs, risk: rg, history, commitment } = d

  const target = x?.targetMetric
  // A forecast in "share of the claim" units cannot be held against a promise in points.
  const promised = ip?.metricUnit === 'normalised_0_1' ? null : promisedChange(target)
  // An NGO is told what to fix in its proposal, not how its spending was screened.
  const signals = flagSignals(d).filter(s => role !== 'ngo' || !s.fraud)
  const seesScores = role !== 'ngo'
  const seesFunding = commitment && (role !== 'company' || commitment.commitment.companyId === companyId)

  return (
    <article className="detail" aria-labelledby="project-title">
      <header className="detail__head">
        <h1 id="project-title" className="detail__title">{p.title}</h1>
        <p className="muted">
          {ngo.name}{p.state ? `, ${p.state}` : ''}. {sectorLabel(p.sector)}.
        </p>
      </header>

      <div className="detail__grid">
        <div className="detail__main">
          {signals.length > 0 && (
            <Section id="why-flagged" title={role === 'ngo' ? 'What the reviewer is checking' : 'Why it is in review'}>
              <ul className="signals">
                {signals.map(s => <li key={s.text}>{s.text}</li>)}
              </ul>
            </Section>
          )}

          {seesFunding && (
            <Section id="funding" title="Funding" hint={fundingHint(commitment)}>
              <CommitmentBlock v={commitment} heading={false} />
              {role === 'ngo' && commitment.commitment.status === 'active' && <ProgressReport projectId={p.id} />}
            </Section>
          )}

          <Section id="proposal" title={role === 'ngo' ? 'Your proposal' : 'Proposal'}>
            <blockquote className="proposal">{p.proposalText}</blockquote>
            {x && (
              <>
                <h3 className="subhead">What the reader picked out</h3>
                <dl className="extract">
                  <div>
                    <dt>Goals</dt>
                    <dd>{x.goals.length
                      ? <ul className="plain">{x.goals.map(g => <li key={g}>{g}</li>)}</ul>
                      : <span className="bad">None stated</span>}</dd>
                  </div>
                  <div>
                    <dt>Measurable target</dt>
                    <dd>
                      {target ? (
                        <>
                          <strong>{metricLabel(target.name)}</strong>
                          {target.baseline != null
                            ? <span className="num"> from {target.baseline} to {target.target} {unitShort(target.unit)}</span>
                            : <span className="num"> to {target.target} {unitShort(target.unit)}<span className="faint"> (no starting value stated)</span></span>}
                        </>
                      ) : <span className="bad">None stated, so progress cannot be checked.</span>}
                    </dd>
                  </div>
                  <div>
                    <dt>Who benefits</dt>
                    <dd>
                      {x.beneficiaries?.count != null
                        ? <><strong className="num">{x.beneficiaries.count.toLocaleString('en-IN')}</strong> {x.beneficiaries.group}</>
                        : <span className={x.beneficiaries?.group ? '' : 'bad'}>
                            {x.beneficiaries?.group ? `${x.beneficiaries.group}, no headcount given` : 'Not stated'}
                          </span>}
                    </dd>
                  </div>
                  <div>
                    <dt>Where</dt>
                    <dd>{[x.geography?.district, x.geography?.state].filter(Boolean).join(', ')
                      || <span className="faint">Not stated</span>}{x.geography?.ruralUrban ? `, ${x.geography.ruralUrban}` : ''}</dd>
                  </div>
                  <div>
                    <dt>Development goals</dt>
                    <dd>
                      <ul className="sdgs">
                        {x.sdgs.map(g => (
                          <li key={g}>
                            <span className="sdg__no" aria-hidden="true">{g}</span>
                            <span className="sdg__name">{sdgName(g)}</span>
                            <Meter value={x.sdgConfidence[g] ?? 0} label={`Confidence for ${sdgName(g)}`}
                              tone={(x.sdgConfidence[g] ?? 0) >= 0.8 ? 'indigo' : 'turmeric'} />
                            <span className="num small">{Math.round((x.sdgConfidence[g] ?? 0) * 100)}%</span>
                          </li>
                        ))}
                      </ul>
                    </dd>
                  </div>
                </dl>
              </>
            )}
          </Section>

          {ip && (
            <Section id="impact" title="Expected impact"
              hint={`${metricLabel(ip.metricName)}, in ${unitShort(ip.metricUnit)}`}>
              <RangeBar low={ip.ciLow} value={ip.predictedValue} high={ip.ciHigh} target={promised} unit={unitShort(ip.metricUnit)} />
              <p className="verdict">{ip.metricUnit === 'normalised_0_1'
                ? `No starting value and target were both read, so this is the share of the claim likely to be delivered: ${ip.predictedValue.toFixed(2)}.`
                : impactVerdict(ip.predictedValue, promised, unitShort(ip.metricUnit))}</p>
              <HowItWorks>
                <p>
                  A gradient-boosted model (XGBoost) trained on past projects forecasts the result. The shaded range holds
                  80% of its likely outcomes; the dot is the most likely one. Normalised impact score: {ip.impactNorm.toFixed(2)} of 1.
                </p>
              </HowItWorks>
            </Section>
          )}

          {seesScores && fs && (
            <Section id="fraud" title="Spending check">
              <div className="meter-row">
                <span>Unusual spending</span>
                <Meter value={fs.anomalyScore} tone={fs.isAnomaly ? 'madder' : fs.anomalyScore > 0.35 ? 'turmeric' : 'neem'} label="Anomaly score" />
                <strong className="num">{fs.anomalyScore.toFixed(2)}</strong>
                {fs.isAnomaly ? <span className="bad small">Anomalous</span> : <span className="small muted">Within normal range</span>}
              </div>
              <HistoryTable rows={history} />
              <HowItWorks>
                <p>
                  An Isolation Forest compares each year of the NGO's spending with its other years and with other NGOs.
                  The score is a percentile: 0.90 means more unusual than 90% of NGOs. Rows that changed two-fold or more are marked.
                </p>
              </HowItWorks>
            </Section>
          )}

          {seesScores && rg && (
            <Section id="score" title="Overall score">
              <ScoreCard rg={rg} />
            </Section>
          )}
        </div>

        <aside className="detail__side" aria-label="Summary">
          <div className="side-card">
            <div className="side-card__top">
              <StatusPill status={p.status} />
              {rg && <Grade grade={rg.grade} />}
            </div>
            <p className="small muted">{NEXT_STEP[p.status]}</p>
            <dl className="side-facts">
              <div><dt>Requested</dt><dd className="num">{inr(p.requestedAmount)}</dd></div>
              <div><dt>Duration</dt><dd>{p.durationMonths} months</dd></div>
              <div><dt>Paid in</dt><dd>{p.numPhases} phases</dd></div>
              {commitment && <div><dt>Funded by</dt><dd>{commitment.companyName}</dd></div>}
              <div><dt>NGO</dt><dd>{ngo.name}</dd></div>
              <div><dt>Registration</dt><dd className="num">{ngo.registrationNo}</dd></div>
              {ngo.establishedYear && <div><dt>Founded</dt><dd className="num">{ngo.establishedYear}</dd></div>}
            </dl>
            {role === 'company' && p.status === 'approved' && (
              <Link to={to('/find')} className="btn btn--turmeric">Compare and fund</Link>
            )}
          </div>

          {role === 'review' && p.status === 'flagged' && !commitment && <Review projectId={p.id} />}
        </aside>
      </div>
    </article>
  )
}

// ---------------------------------------------------------------- decisions and reports

function Review({ projectId }: { projectId: number }) {
  const { act } = useExchange()
  const [note, setNote] = useState('')
  const decide = (approve: boolean) =>
    act(approve ? 'Project approved' : 'Project rejected', api => api.reviewProject(projectId, approve, note.trim() || null))
  return (
    <form className="side-card decision" aria-labelledby="decision-h" onSubmit={e => { e.preventDefault(); decide(true) }}>
      <h2 id="decision-h">Your decision</h2>
      <p className="small muted">Approving lets companies fund it. Rejecting closes it. Rescoring never overrides your decision.</p>
      <div className="field">
        <label htmlFor="review-note">What you checked</label>
        <textarea id="review-note" className="input" value={note} maxLength={500} rows={3}
          placeholder="e.g. spending explained by a one-off grant" onChange={e => setNote(e.target.value)} />
      </div>
      <div className="decision__actions">
        <button className="btn" type="submit">Approve</button>
        <button className="btn btn--danger" type="button" onClick={() => decide(false)}>Reject</button>
      </div>
    </form>
  )
}

/** What an NGO files each month; the company's impact views recompute from it. */
function ProgressReport({ projectId }: { projectId: number }) {
  const { act } = useExchange()
  const [value, setValue] = useState('')
  return (
    <form className="inline-form progress-report" onSubmit={e => {
      e.preventDefault()
      const v = Number(value)
      if (value && Number.isFinite(v)) act('Monthly progress reported', api => api.reportImpact(projectId, v)).then(r => { if (r.ok) setValue('') })
    }}>
      <div className="field">
        <label htmlFor="progress">Progress this month</label>
        <input id="progress" className="input" type="number" step="any" inputMode="decimal" required
          value={value} onChange={e => setValue(e.target.value)} />
      </div>
      <button className="btn btn--quiet" type="submit">Report progress</button>
    </form>
  )
}

function fundingHint({ commitment: c, companyName, phases }: CommitmentView): string {
  const paid = phases.filter(p => p.status === 'released').reduce((t, p) => t + p.amount, 0)
  if (c.status === 'completed') return `${companyName} paid all ${inrCompact(c.amount)}, phase by phase.`
  if (c.status === 'cancelled') {
    return `${companyName} ended its funding. ${inrCompact(paid)} was paid; the other ${inrCompact(c.amount - paid)} went back to its budget.`
  }
  return `${companyName} has committed ${inrCompact(c.amount)}.`
}

function impactVerdict(predicted: number, promised: number | null, unit: string): string {
  if (promised === null) return 'The proposal states no measurable target, so there is nothing to hold this prediction against.'
  const ratio = predicted / promised
  const gap = `${num(predicted, 1)} against ${num(promised, 1)} ${unit} promised`
  if (ratio >= 1) return `Likely to deliver what it promises: ${gap}.`
  if (ratio >= 0.85) return `Close to the promise, slightly under: ${gap}.`
  return `Likely to fall short of the promise: ${gap}.`
}

function flagSignals(d: ProjectDetail): { text: string; fraud?: boolean }[] {
  if (d.project.status !== 'flagged' && d.risk?.decision !== 'flagged') return []
  const out: { text: string; fraud?: boolean }[] = []
  if (d.fraud?.isAnomaly) out.push({ text: `The NGO's spending history is anomalous (score ${d.fraud.anomalyScore.toFixed(2)}).`, fraud: true })
  else if (d.fraud && d.fraud.anomalyScore > 0.35) out.push({ text: `Spending history is somewhat unusual (score ${d.fraud.anomalyScore.toFixed(2)}).`, fraud: true })
  if (!d.extraction?.targetMetric) out.push({ text: 'The proposal states no measurable target.' })
  if (d.prediction && d.prediction.impactNorm < 0.4) out.push({ text: `Expected impact is low (${d.prediction.impactNorm.toFixed(2)} on a 0 to 1 scale).` })
  if (d.risk && d.risk.sdgConfidence < 0.8) out.push({ text: `It is unclear which development goal this serves (confidence ${d.risk.sdgConfidence.toFixed(2)}).` })
  if (d.risk) out.push({ text: `Overall score ${d.risk.compositeScore.toFixed(2)}, grade ${d.risk.grade}.`, fraud: true })
  return out
}

// ---------------------------------------------------------------- spending history

const HISTORY_ROWS: { label: string; get: (h: SpendingHistory) => number | null; fmt: (n: number) => string }[] = [
  { label: 'Total spend', get: h => h.totalSpend, fmt: inrCompact },
  { label: 'Admin share of spend', get: h => h.adminExpenseRatio, fmt: n => `${(n * 100).toFixed(1)}%` },
  { label: 'Spend against schedule', get: h => h.burnRateVsSchedule, fmt: n => `${n.toFixed(2)}x` },
  { label: 'Shift in spending mix', get: h => h.categoryMixDrift, fmt: n => n.toFixed(2) },
  { label: 'Round-number invoices', get: h => h.roundNumberFreq, fmt: n => `${(n * 100).toFixed(0)}%` },
  { label: 'Spend with top vendors', get: h => h.vendorConcentration, fmt: n => `${(n * 100).toFixed(0)}%` },
  { label: 'Days to file a report', get: h => h.reportLatencyDays, fmt: n => `${n}` },
  { label: 'Cost per beneficiary', get: h => h.costPerBeneficiary, fmt: n => inr(n) },
]

function HistoryTable({ rows }: { rows: SpendingHistory[] }) {
  const sorted = [...rows].sort((a, b) => a.fy.localeCompare(b.fy))
  if (sorted.length < 2) return null
  const [before, after] = [sorted.at(-2)!, sorted.at(-1)!]
  return (
    <TableScroll label="Spending pattern rows">
    <table className="table history">
      <caption className="sr-only">Spending patterns, {before.fy} against {after.fy}</caption>
      <thead>
        <tr><th scope="col">Pattern</th><th scope="col" className="r">{before.fy}</th><th scope="col" className="r">{after.fy}</th><th scope="col" className="r">Change</th></tr>
      </thead>
      <tbody>
        {HISTORY_ROWS.map(r => {
          const a = r.get(before), b = r.get(after)
          if (a == null || b == null) return null
          const ratio = a === 0 ? 1 : b / a
          const jump = ratio >= 2 || ratio <= 0.5
          return (
            <tr key={r.label} data-jump={jump || undefined}>
              <th scope="row">{r.label}</th>
              <td className="r num">{r.fmt(a)}</td>
              <td className="r num">{r.fmt(b)}</td>
              <td className="r num">{ratio >= 10 ? `${Math.round(ratio)}x` : `${num(ratio, 1)}x`}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
    </TableScroll>
  )
}

// ---------------------------------------------------------------- composite score

const WEIGHTS = { impact: 0.45, trust: 0.3, sdg: 0.15, track: 0.1 }

function ScoreCard({ rg }: { rg: NonNullable<ProjectDetail['risk']> }) {
  const parts = [
    { key: 'impact', label: 'Impact', value: WEIGHTS.impact * rg.impactNorm, tone: 'indigo' as const, note: `0.45 x ${rg.impactNorm.toFixed(2)}` },
    { key: 'trust', label: 'Trust in spending', value: WEIGHTS.trust * (1 - rg.fraudScore), tone: 'neem' as const, note: `0.30 x ${(1 - rg.fraudScore).toFixed(2)}` },
    { key: 'sdg', label: 'Goal confidence', value: WEIGHTS.sdg * rg.sdgConfidence, tone: 'turmeric' as const, note: `0.15 x ${rg.sdgConfidence.toFixed(2)}` },
    { key: 'track', label: 'NGO track record', value: WEIGHTS.track * rg.ngoTrackRecord, tone: 'linen' as const, note: `0.10 x ${rg.ngoTrackRecord.toFixed(2)}` },
  ]
  const recomputed = parts.reduce((t, s) => t + s.value, 0)
  const drift = Math.abs(recomputed - rg.compositeScore) > 0.005

  return (
    <div className="score">
      <div className="score__verdict">
        <Grade grade={rg.grade} large />
        <div>
          <p className="score__num display">{rg.compositeScore.toFixed(2)}</p>
          <p className="muted small">Scoring decision: {STATUS_LABEL[rg.decision].toLowerCase()}</p>
        </div>
      </div>
      <div className="score__body">
        <ScoreStack segments={parts} total={recomputed} caption="How the four inputs add up to the overall score" />
        {drift && (
          <p className="note small">
            These weights give {recomputed.toFixed(2)}, not the stored {rg.compositeScore.toFixed(2)}: the stored score is a
            placeholder from the seed data. Resetting the demo data in the review console rescores it with the models.
          </p>
        )}
        <HowItWorks>
          <p>
            The score is computed in the database by <code>fn_grade_project</code>: 45% expected impact, 30% trust in the
            NGO's spending, 15% confidence in the development goals and 10% the NGO's track record. Grade A is 0.84 or
            more, B 0.77, C 0.69. Only an A or B with no spending flag and a measurable target is approved
            automatically; everything else goes to a reviewer.
          </p>
        </HowItWorks>
      </div>
    </div>
  )
}
