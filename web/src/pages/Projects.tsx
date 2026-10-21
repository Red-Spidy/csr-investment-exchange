import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Cloth } from '../components/Cloth'
import { Grade, Meter, PageHead, RangeBar, ScoreStack, Section, StatusPill, TableScroll, Loading } from '../components/ui'
import type { CommitmentView, ProjectDetail, Sector } from '../data/api'
import { useExchange, useQuery } from '../data/store'
import type { SpendingHistory } from '../data/types'
import { commitmentBands } from '../lib/bands'
import { promisedChange } from '../lib/claim'
import { inr, inrCompact, num } from '../lib/format'
import { metricLabel, sdgName, sectorLabel, unitShort } from '../lib/labels'

type Filter = 'all' | 'approved' | 'flagged' | 'funded'
const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'approved', label: 'Approved' },
  { id: 'funded', label: 'Funded' },
  { id: 'flagged', label: 'Flagged' },
]

export function Projects() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data: rows } = useQuery(api => api.scorecard())
  const [filter, setFilter] = useState<Filter>('all')
  const [submitting, setSubmitting] = useState(false)
  const ngos = useMemo(() => [...new Map((rows ?? []).map(r => [r.ngoId, r.ngoName])).entries()]
    .map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name)), [rows])

  const visible = useMemo(() => (rows ?? []).filter(r =>
    filter === 'all' ? true
    : filter === 'funded' ? ['matched', 'active', 'closed'].includes(r.status)
    : r.status === filter), [rows, filter])

  const selectedId = Number(id) || visible[0]?.projectId || rows?.[0]?.projectId

  return (
    <>
      <PageHead
        title="Every proposal is scored before it can get money."
        lead="Models read each proposal, predict its impact and screen the NGO's spending history. They produce evidence. A person decides, and SQL moves the money."
      >
        <button className="btn" aria-expanded={submitting} onClick={() => setSubmitting(v => !v)}>
          {submitting ? 'Close the form' : 'Submit a proposal'}
        </button>
      </PageHead>

      {submitting && ngos.length > 0 && (
        <SubmitProposal ngos={ngos} onSubmitted={pid => { setSubmitting(false); navigate(`/projects/${pid}`) }} />
      )}

      <div className="split">
        <div className="split__list">
          <div className="filters" role="group" aria-label="Filter projects by status">
            {FILTERS.map(f => (
              <button key={f.id} className="filter" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                {f.label}
              </button>
            ))}
          </div>

          <ul className="rows">
            {visible.map(r => (
              <li key={r.projectId}>
                <button
                  className="row" aria-current={r.projectId === selectedId || undefined}
                  onClick={() => navigate(`/projects/${r.projectId}`)}
                >
                  <Grade grade={r.grade} />
                  <span className="row__main">
                    <span className="row__title">{r.title}</span>
                    <span className="row__meta">{r.ngoName}, {r.state}</span>
                  </span>
                  <span className="row__side">
                    <span className="num">{inrCompact(r.requestedAmount)}</span>
                    <StatusPill status={r.status} />
                  </span>
                </button>
              </li>
            ))}
            {!rows && <li><Loading>Loading projects</Loading></li>}
            {rows && visible.length === 0 && (
              <li className="empty"><h3>No projects here</h3><p>Try another filter.</p></li>
            )}
          </ul>
        </div>

        <div className="split__detail">
          {selectedId ? <Detail projectId={selectedId} /> : null}
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- detail

function Detail({ projectId }: { projectId: number }) {
  const { data: d } = useQuery(api => api.projectDetail(projectId), [projectId])
  if (!d) return <Loading>Loading project</Loading>
  return <ProjectView d={d} key={d.project.id} />
}

function ProjectView({ d }: { d: ProjectDetail }) {
  const { project: p, ngo, extraction: x, prediction: ip, fraud: fs, risk: rg, history, commitment } = d

  const target = x?.targetMetric
  // A forecast in "share of the claim" units cannot be held against a promise in points.
  const promised = ip?.metricUnit === 'normalised_0_1' ? null : promisedChange(target)
  const signals = flagSignals(d)

  return (
    <article className="detail" aria-labelledby="project-title">
      <header className="detail__head">
        <div className="detail__badges">
          <StatusPill status={p.status} />
          <span className="faint small">{sectorLabel(p.sector)}</span>
        </div>
        <h2 id="project-title" className="detail__title">{p.title}</h2>
        <p className="muted">
          {ngo.name}, {p.state}. Registered {ngo.registrationNo}{ngo.establishedYear ? `, founded ${ngo.establishedYear}` : ''}.
        </p>
        <dl className="facts">
          <div><dt>Asking for</dt><dd className="num">{inr(p.requestedAmount)}</dd></div>
          <div><dt>Runs for</dt><dd>{p.durationMonths} months</dd></div>
          <div><dt>Paid in</dt><dd>{p.numPhases} phases</dd></div>
        </dl>
      </header>

      {signals.length > 0 && (
        <Section id="why-flagged" title="Why it was held back">
          <ul className="signals">
            {signals.map(s => <li key={s}>{s}</li>)}
          </ul>
        </Section>
      )}

      <Section id="proposal" title="What the proposal says and what the model read">
        <blockquote className="proposal">{p.proposalText}</blockquote>
        {x && (
          <dl className="extract">
            <div>
              <dt>Goals</dt>
              <dd><ul className="plain">{x.goals.map(g => <li key={g}>{g}</li>)}</ul></dd>
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
              <dd>{[x.geography?.district, x.geography?.state].filter(Boolean).join(', ')}{x.geography?.ruralUrban ? `, ${x.geography.ruralUrban}` : ''}</dd>
            </div>
            <div>
              <dt>Goals it serves</dt>
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
        )}
      </Section>

      {ip && (
        <Section id="impact" title="What it is likely to achieve"
          hint={`${metricLabel(ip.metricName)}, measured in ${unitShort(ip.metricUnit)}. The shaded range holds 80% of the model's outcomes.`}>
          <RangeBar low={ip.ciLow} value={ip.predictedValue} high={ip.ciHigh} target={promised} unit={unitShort(ip.metricUnit)} />
          <p className="verdict">{ip.metricUnit === 'normalised_0_1'
            ? `No baseline and target were both read, so the forecast is the share of the claim the model expects to be delivered: ${ip.predictedValue.toFixed(2)}.`
            : impactVerdict(ip.predictedValue, promised, unitShort(ip.metricUnit))}</p>
          <div className="meter-row">
            <span>Normalised impact score</span>
            <Meter value={ip.impactNorm} label="Normalised impact score" />
            <strong className="num">{ip.impactNorm.toFixed(2)}</strong>
          </div>
        </Section>
      )}

      {fs && (
        <Section id="fraud" title="Does the spending look right?"
          hint="An Isolation Forest compares each year of the NGO's spending with its other years and with other NGOs. The score is a percentile: 0.9 means more unusual than 90% of NGOs.">
          <div className="meter-row">
            <span>Anomaly score</span>
            <Meter value={fs.anomalyScore} tone={fs.isAnomaly ? 'madder' : fs.anomalyScore > 0.35 ? 'turmeric' : 'neem'} label="Anomaly score" />
            <strong className="num">{fs.anomalyScore.toFixed(2)}</strong>
            {fs.isAnomaly && <span className="bad small">Flagged as anomalous</span>}
          </div>
          <HistoryTable rows={history} />
        </Section>
      )}

      {rg && (
        <Section id="score" title="Overall score">
          <ScoreCard rg={rg} />
        </Section>
      )}

      {p.status === 'flagged' && !commitment && <Review projectId={p.id} />}

      {commitment && (
        <Section id="funding" title="Funding"
          hint={fundingHint(commitment)}>
          <Cloth bands={commitmentBands(commitment)} height={56} label="Funding by phase" />
          <p className="feed__more"><Link to="/funds" className="link-btn">Open the milestones</Link></p>
        </Section>
      )}
    </article>
  )
}

// ---------------------------------------------------------------- review and submission

function Review({ projectId }: { projectId: number }) {
  const { act } = useExchange()
  const [note, setNote] = useState('')
  const decide = (approve: boolean) =>
    act(`${approve ? 'Approve' : 'Reject'} project ${projectId}`, api => api.reviewProject(projectId, approve, note.trim() || null))
  return (
    <Section id="review" title="Your decision"
      hint="The grade sent this project to a person. Approving puts it in the matching pool; rejecting closes it. The decision is kept: running the models again will not overturn it.">
      <form className="inline-form" onSubmit={e => { e.preventDefault(); decide(true) }}>
        <div className="field">
          <label htmlFor="review-note">What you checked</label>
          <input id="review-note" className="input" value={note} maxLength={500}
            placeholder="e.g. spending explained by a one-off grant" onChange={e => setNote(e.target.value)} />
        </div>
        <button className="btn" type="submit">Approve</button>
        <button className="btn btn--danger" type="button" onClick={() => decide(false)}>Reject</button>
      </form>
    </Section>
  )
}

const SECTORS: Sector[] = ['education', 'healthcare', 'water_sanitation', 'environment', 'livelihood']

function SubmitProposal({ ngos, onSubmitted }: {
  ngos: { id: number; name: string }[]
  onSubmitted: (projectId: number) => void
}) {
  const { act, source } = useExchange()
  const [f, setF] = useState({ ngoId: ngos[0].id, title: '', sector: 'education' as Sector, state: '',
    amount: '', duration: '12', phases: '3', text: '' })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(v => ({ ...v, [k]: e.target.value }))

  return (
    <Section id="submit" title="Submit a proposal"
      hint={source === 'live'
        ? 'BERT reads it, the Isolation Forest checks the NGO\'s spending, XGBoost forecasts the impact, and fn_grade_project decides. Takes a few seconds; the first one also loads the models.'
        : 'Scoring needs the API, because the models run in Python. Start it with make api.'}>
      <form className="proposal-form" onSubmit={async e => {
        e.preventDefault()
        const out = await act(`Submit proposal: ${f.title}`, api => api.submitProposal({
          ngoId: Number(f.ngoId), title: f.title.trim(), proposalText: f.text.trim(), sector: f.sector,
          state: f.state.trim() || null, requestedAmount: Number(f.amount),
          durationMonths: Number(f.duration), numPhases: Number(f.phases),
        }))
        if (out.ok && out.projectId) onSubmitted(out.projectId)
      }}>
        <div className="field">
          <label htmlFor="sp-ngo">NGO</label>
          <select id="sp-ngo" className="select" value={f.ngoId} onChange={set('ngoId')}>
            {ngos.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="sp-title">Project title</label>
          <input id="sp-title" className="input" required minLength={3} maxLength={200} value={f.title} onChange={set('title')} />
        </div>
        <div className="field">
          <label htmlFor="sp-sector">Sector</label>
          <select id="sp-sector" className="select" value={f.sector} onChange={set('sector')}>
            {SECTORS.map(s => <option key={s} value={s}>{sectorLabel(s)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="sp-state">State</label>
          <input id="sp-state" className="input" maxLength={80} value={f.state} onChange={set('state')} />
        </div>
        <div className="field">
          <label htmlFor="sp-amount">Amount requested (₹)</label>
          <input id="sp-amount" className="input" type="number" required min={1} step={1000} inputMode="numeric"
            value={f.amount} onChange={set('amount')} />
        </div>
        <div className="field">
          <label htmlFor="sp-duration">Duration (months)</label>
          <input id="sp-duration" className="input" type="number" required min={1} max={120} value={f.duration} onChange={set('duration')} />
        </div>
        <div className="field">
          <label htmlFor="sp-phases">Paid in phases</label>
          <input id="sp-phases" className="input" type="number" required min={1} max={12} value={f.phases} onChange={set('phases')} />
        </div>
        <div className="field proposal-form__text">
          <label htmlFor="sp-text">The proposal, in the NGO's own words</label>
          <textarea id="sp-text" className="input" required minLength={50} maxLength={8000} rows={7}
            placeholder="What you will do, where, for whom, what will change and by how much, how long it takes and what it costs."
            value={f.text} onChange={set('text')} />
        </div>
        <div className="proposal-form__actions">
          <button className="btn" type="submit">Submit and score</button>
        </div>
      </form>
    </Section>
  )
}

function fundingHint({ commitment: c, companyName, phases }: CommitmentView): string {
  const paid = phases.filter(p => p.status === 'released').reduce((t, p) => t + p.amount, 0)
  if (c.status === 'completed') return `${companyName} paid all ${inrCompact(c.amount)}, phase by phase.`
  if (c.status === 'cancelled') {
    return `${companyName} terminated this commitment. ${inrCompact(paid)} was paid; the other ${inrCompact(c.amount - paid)} went back to its budget.`
  }
  return `${companyName} has locked ${inrCompact(c.amount)} for this project.`
}

function impactVerdict(predicted: number, promised: number | null, unit: string): string {
  if (promised === null) return 'The proposal states no measurable target, so there is nothing to hold this prediction against.'
  const ratio = predicted / promised
  const gap = `${predicted} against ${promised} ${unit} promised`
  if (ratio >= 1) return `Likely to deliver what it promises: ${gap}.`
  if (ratio >= 0.85) return `Close to the promise, slightly under: ${gap}.`
  return `Likely to fall short of the promise: ${gap}.`
}

function flagSignals(d: ProjectDetail): string[] {
  if (d.project.status !== 'flagged' && d.risk?.decision !== 'flagged') return []
  const out: string[] = []
  if (d.fraud?.isAnomaly) out.push(`The NGO's spending history is anomalous (score ${d.fraud.anomalyScore.toFixed(2)}).`)
  else if (d.fraud && d.fraud.anomalyScore > 0.35) out.push(`Spending history is somewhat unusual (score ${d.fraud.anomalyScore.toFixed(2)}).`)
  if (!d.extraction?.targetMetric) out.push('The proposal states no measurable target.')
  if (d.prediction && d.prediction.impactNorm < 0.4) out.push(`Predicted impact is low (${d.prediction.impactNorm.toFixed(2)} on a 0 to 1 scale).`)
  if (d.risk && d.risk.sdgConfidence < 0.8) out.push(`The model is unsure which development goal this serves (confidence ${d.risk.sdgConfidence.toFixed(2)}).`)
  if (d.risk) out.push(`Overall score ${d.risk.compositeScore.toFixed(2)}, grade ${d.risk.grade}.`)
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
          <p className="muted small">Decision: {rg.decision}</p>
        </div>
      </div>
      <div className="score__body">
        <ScoreStack segments={parts} total={recomputed} caption="How the four inputs add up to the overall score" />
        {drift && (
          <p className="note small">
            These weights give {recomputed.toFixed(2)}, not the stored {rg.compositeScore.toFixed(2)}. The stored score is a
            placeholder from the seed file until the risk model is retrained.
          </p>
        )}
      </div>
    </div>
  )
}
