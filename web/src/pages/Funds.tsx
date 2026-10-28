import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Cloth, ClothLegend } from '../components/Cloth'
import { HowItWorks, Kpis, PageHead, Pill, Section, TableScroll, Loading } from '../components/ui'
import type { CommitmentView } from '../data/api'
import { usePortal } from '../data/portal'
import { useExchange, useQuery } from '../data/store'
import type { CommitmentStatus, FundPhase, Milestone } from '../data/types'
import { commitmentBands, shortCompany, shortTitle, sumByTone } from '../lib/bands'
import { dateShort, inr, inrCompact, timeShort } from '../lib/format'
import { TXN_LABEL, TXN_TONE } from '../lib/labels'

/** Evidence waiting for a reviewer comes first, then work in progress, then finished commitments. */
function urgency(v: CommitmentView) {
  if (v.milestones.some(m => m.verification === 'submitted')) return 0
  if (v.phases.some(p => p.status === 'held') && v.commitment.status === 'active') return 1
  return v.commitment.status === 'active' ? 2 : 3
}

/** The company's Funding page, or every commitment in the review console's Milestones. */
export function Funds() {
  const { role, companyId, to } = usePortal()
  const { data: companies } = useQuery(api => api.companies())
  const { data: commitments } = useQuery(api => api.commitments())
  const { data: ledger } = useQuery(api => api.ledger())
  const { data: audit } = useQuery(api => api.audit())

  const reviewing = role === 'review'
  const company = companies?.find(c => c.id === companyId)
  const mine = [...(commitments ?? [])]
    .filter(c => reviewing || c.commitment.companyId === companyId)
    .sort((a, b) => urgency(a) - urgency(b) || b.commitment.id - a.commitment.id)
  const mineIds = new Set(mine.map(c => c.commitment.id))
  const entries = [...(ledger ?? [])].filter(l => mineIds.has(l.commitmentId)).reverse()
  const auditRows = [...(audit ?? [])].filter(a =>
    (a.entity === 'commitment' && mineIds.has(a.entityId))
    || (a.entity === 'milestone' && mine.some(c => c.milestones.some(m => m.id === a.entityId)))).reverse()

  const page = reviewing ? 'Milestones' : 'Funding'
  if ((!reviewing && !company) || !commitments || !ledger || !audit) return <Loading page={page}>Loading {page.toLowerCase()}</Loading>

  const phases = mine.flatMap(c => c.phases)
  const sum = (pred: (p: FundPhase) => boolean) => phases.filter(pred).reduce((t, p) => t + p.amount, 0)
  const toVerify = mine.flatMap(c => c.milestones).filter(m => m.verification === 'submitted').length

  return (
    <>
      <PageHead title={page}
        lead={reviewing
          ? 'Verify an NGO\'s evidence to release that phase, or fail it to hold the money.'
          : 'Money you have committed, paid out one phase at a time as each milestone is verified.'}>
        {!reviewing && <Link to={to('/find')} className="btn btn--turmeric">Fund a project</Link>}
      </PageHead>

      <Kpis items={[
        { label: 'Committed', value: inrCompact(phases.reduce((t, p) => t + p.amount, 0) - sum(p => p.status === 'terminated')) },
        { label: 'Released', value: inrCompact(sum(p => p.status === 'released')) },
        { label: 'Waiting on milestones', value: inrCompact(sum(p => p.status === 'locked')) },
        reviewing
          ? { label: 'Evidence to verify', value: toVerify, tone: toVerify ? 'turmeric' : undefined }
          : { label: 'Held', value: inrCompact(sum(p => p.status === 'held')), tone: sum(p => p.status === 'held') ? 'madder' : undefined },
      ]} />

      {mine.length === 0 ? (
        <div className="empty">
          <h3>{reviewing ? 'Nothing is funded yet' : 'You have not funded a project yet'}</h3>
          <p>Once a company funds a project, its phases and milestones appear here.</p>
          {!reviewing && <Link to={to('/find')} className="btn btn--turmeric">Find a project to fund</Link>}
        </div>
      ) : (
        <div className="commitments">
          {mine.map(v => <CommitmentBlock key={v.commitment.id} v={v} />)}
        </div>
      )}

      <Section id="ledger" title="Ledger" hint={`${entries.length} entries, newest first`}>
        {entries.length === 0 ? (
          <div className="empty"><h3>No money has moved yet</h3><p>Funding a project writes the first entry.</p></div>
        ) : (
          <TableScroll label="Ledger rows">
          <table className="table register ledger">
            <thead>
              <tr><th scope="col">Entry</th><th scope="col">When</th><th scope="col">Type</th><th scope="col">Note</th><th scope="col" className="r">Amount</th></tr>
            </thead>
            <tbody>
              {entries.map(l => (
                <tr key={l.id}>
                  <td className="num faint">{l.id}</td>
                  <td className="nowrap">{dateShort(l.createdAt)}, {timeShort(l.createdAt)}</td>
                  <td><Pill tone={TXN_TONE[l.type]}>{TXN_LABEL[l.type]}</Pill></td>
                  <td>{l.note}</td>
                  <td className="r num"><strong>{inr(l.amount)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableScroll>
        )}

        <HowItWorks>
          <p>
            Verifying a milestone sets one flag. A trigger in the database then releases that phase's money and
            writes the ledger entry, so no person or model moves money directly. The ledger is append-only: the
            database refuses to edit or delete an entry.
          </p>
          {auditRows.length > 0 && (
            <TableScroll label="Audit log rows">
            <table className="table ledger">
              <caption className="sr-only">Audit log</caption>
              <thead><tr><th scope="col">When</th><th scope="col">Record</th><th scope="col">Action</th><th scope="col">Detail</th></tr></thead>
              <tbody>
                {auditRows.map(a => (
                  <tr key={a.id}>
                    <td className="nowrap">{dateShort(a.createdAt)}, {timeShort(a.createdAt)}</td>
                    <td>{a.entity} {a.entityId}</td>
                    <td>{a.action.replace(/_/g, ' ')}</td>
                    <td className="code">{JSON.stringify(a.detail)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </TableScroll>
          )}
        </HowItWorks>
      </Section>
    </>
  )
}

// ---------------------------------------------------------------- one commitment

const COMMITMENT_PILL: Record<CommitmentStatus, { tone: 'neem' | 'indigo' | 'madder'; label: string }> = {
  active: { tone: 'indigo', label: 'In progress' },
  completed: { tone: 'neem', label: 'Completed' },
  cancelled: { tone: 'madder', label: 'Terminated' },
}

/** A commitment's money by phase. `heading` is false on a project page, which already names the project. */
export function CommitmentBlock({ v, heading = true, measure }: {
  v: CommitmentView; heading?: boolean
  /** What a milestone's result is counted in, for the NGO's evidence form. */
  measure?: string
}) {
  const { role, to } = usePortal()
  const bands = commitmentBands(v)
  const totals = sumByTone(bands)
  const legend = (['released', 'review', 'locked', 'held', 'returned'] as const)
    .filter(t => totals[t] > 0).map(t => ({ tone: t, value: inrCompact(totals[t]) }))
  const { status } = v.commitment
  const summary = status === 'cancelled'
    ? `Terminated. ${inr(totals.released)} was paid and ${inr(totals.returned)} went back to ${shortCompany(v.companyName)}.`
    : `${inr(v.commitment.amount)} from ${v.companyName}, in ${v.phases.length} phases.`

  return (
    <section className="commit" aria-labelledby={`c${v.commitment.id}`}>
      <header className="commit__head">
        <div>
          {heading ? (
            <h2 id={`c${v.commitment.id}`}><Link to={to(`/projects/${v.project.id}`)}>{v.project.title}</Link></h2>
          ) : (
            <h2 id={`c${v.commitment.id}`} className="sr-only">Funding</h2>
          )}
          {heading && <p className="muted small">{v.ngoName}. {summary}</p>}
        </div>
        <Pill tone={COMMITMENT_PILL[status].tone}>{COMMITMENT_PILL[status].label}</Pill>
      </header>

      <Cloth bands={bands} height={heading ? 48 : 40} label={`${v.project.title}: ${legend.map(l => `${l.tone} ${l.value}`).join(', ')}`} />
      <ClothLegend items={legend} />

      <ol className="phases">
        {v.phases.map(p => {
          const ms = v.milestones.find(m => m.phaseNo === p.phaseNo)!
          const before = v.phases.filter(x => x.phaseNo < p.phaseNo)
          const blocked = before.some(x => x.status !== 'released')
          return <PhaseCard key={p.id} phase={p} ms={ms} blockedBy={blocked ? before.find(x => x.status !== 'released')! : null}
            prevMetric={v.milestones.find(m => m.phaseNo === p.phaseNo - 1)?.reportedMetric ?? null} measure={measure} />
        })}
      </ol>

      {status === 'active' && role === 'company' && (
        // Keyed on the held phase so a fresh failure brings its own prefilled reason.
        <EndCommitment key={v.phases.find(p => p.status === 'held')?.id ?? 0} v={v}
          unreleased={totals.locked + totals.review + totals.held} />
      )}
      {status === 'active' && role !== 'company' && v.phases.some(p => p.status === 'held') && (
        <p className="note small">
          A phase failed verification, so its money is held. {shortCompany(v.companyName)} decides whether to end the
          commitment, which returns the unreleased money to its budget.
        </p>
      )}
    </section>
  )
}

/**
 * fn_terminate_commitment. Open by default when a phase is held, because ending the
 * commitment is then the only way the held money can move; tucked away otherwise.
 */
function EndCommitment({ v, unreleased }: { v: CommitmentView; unreleased: number }) {
  const { act } = useExchange()
  const held = v.phases.find(p => p.status === 'held')
  const [reason, setReason] = useState(held ? `Phase ${held.phaseNo} failed verification.` : '')
  const [confirming, setConfirming] = useState(false)
  const company = shortCompany(v.companyName)
  const id = `end${v.commitment.id}`

  const form = (
    <form className="end" onSubmit={e => { e.preventDefault(); if (reason.trim()) setConfirming(true) }}>
      <p className="small">
        Ending the commitment is final. The {inrCompact(unreleased)} not yet released goes back to
        {' '}{company}'s budget, and what was already paid stays paid.
      </p>
      <div className="field">
        <label htmlFor={id}>Reason (recorded in the ledger)</label>
        <input id={id} className="input" value={reason} maxLength={500} required
          onChange={e => { setReason(e.target.value); setConfirming(false) }} />
      </div>
      {confirming ? (
        <div className="confirm confirm--danger" role="group" aria-label={`Confirm ending ${shortTitle(v.project.title)}`}>
          <p>
            Return <strong>{inr(unreleased)}</strong> to {company} and close {shortTitle(v.project.title)}?
            The project cannot be funded again, and this cannot be undone.
          </p>
          <div className="confirm__actions">
            <button type="button" className="btn btn--danger"
              onClick={() => act('Commitment ended', api => api.terminateCommitment(v.commitment.id, reason))}>
              End and refund
            </button>
            <button type="button" className="btn btn--quiet" autoFocus onClick={() => setConfirming(false)}>Keep it</button>
          </div>
        </div>
      ) : (
        <button className="btn btn--small btn--danger" type="submit">End and refund {inrCompact(unreleased)}</button>
      )}
    </form>
  )

  if (held) {
    return (
      <div className="end-box" role="group" aria-labelledby={`${id}h`}>
        <h3 id={`${id}h`}>Phase {held.phaseNo} failed verification</h3>
        <p className="small muted">
          Its {inrCompact(held.amount)} is held and later phases cannot open. A failed verification is final, so this
          money moves only if you end the commitment.
        </p>
        {form}
      </div>
    )
  }
  return (
    <details className="how end-early">
      <summary>End this commitment early</summary>
      <div className="how__body">{form}</div>
    </details>
  )
}

/** One phase: what it pays, its milestone, and the one action the signed-in role can take on it. */
export function PhaseCard({ phase, ms, blockedBy, prevMetric, measure }: {
  phase: FundPhase; ms: Milestone; blockedBy: FundPhase | null; prevMetric: number | null; measure?: string
}) {
  const { act } = useExchange()
  const { role } = usePortal()
  const [metric, setMetric] = useState('')
  const label = `Phase ${phase.phaseNo}`

  const tone = phase.status === 'released' ? 'released'
    : phase.status === 'held' ? 'held'
    : phase.status === 'terminated' ? 'returned'
    : ms.verification === 'submitted' ? 'review' : 'locked'

  return (
    <li className="phase weave-edge" data-tone={tone}>
      <div className="phase__top">
        <h3>{label}</h3>
        <strong className="num">{inrCompact(phase.amount)}</strong>
      </div>
      <p className="faint small">{ms.description}, due {dateShort(ms.dueDate)}</p>

      {phase.status === 'released' && (
        <div className="phase__state">
          <Pill tone="indigo">Released</Pill>
          <p className="small">
            Result reported: {ms.reportedMetric}. Verified{phase.releasedAt ? ` and paid ${dateShort(phase.releasedAt)}.` : '.'}
          </p>
        </div>
      )}

      {phase.status === 'held' && (
        <div className="phase__state">
          <Pill tone="madder">Held</Pill>
          <p className="small">Verification failed. The {inrCompact(phase.amount)} is not paid.</p>
        </div>
      )}

      {phase.status === 'terminated' && (
        <div className="phase__state">
          <Pill tone="linen">Refunded</Pill>
          <p className="small">Never paid. The commitment ended and the money went back to the company.</p>
        </div>
      )}

      {phase.status === 'locked' && ms.verification === 'submitted' && (
        <div className="phase__state">
          <Pill tone="turmeric">Evidence submitted</Pill>
          <p className="small">
            Result reported: {ms.reportedMetric}.
            {role === 'review'
              ? ` Verifying pays ${inrCompact(phase.amount)} to the NGO; failing holds it.`
              : ' Waiting for the exchange reviewer to verify it.'}
          </p>
          {role === 'review' && (
            <div className="phase__actions">
              <button className="btn btn--small"
                onClick={() => act(`${label} verified`, api => api.verifyMilestone(ms.id))}>Verify and release</button>
              <button className="btn btn--small btn--danger"
                onClick={() => act(`${label} failed`, api => api.failMilestone(ms.id))}>Fail and hold</button>
            </div>
          )}
        </div>
      )}

      {phase.status === 'locked' && ms.verification === 'pending' && (
        blockedBy ? (
          <div className="phase__state">
            <Pill tone="linen">Locked</Pill>
            <p className="small">
              {blockedBy.status === 'held'
                ? `Cannot open while phase ${blockedBy.phaseNo} is held.`
                : `Opens once phase ${blockedBy.phaseNo} is verified.`}
            </p>
          </div>
        ) : role === 'ngo' ? (
          <form className="phase__state" onSubmit={e => {
            e.preventDefault()
            const value = Number(metric)
            if (Number.isFinite(value)) act(`Evidence submitted for ${label.toLowerCase()}`, api => api.submitEvidence(ms.id, value))
          }}>
            <Pill tone="linen">Evidence due</Pill>
            <div className="field">
              <label htmlFor={`m${ms.id}`}>Result achieved so far</label>
              <input id={`m${ms.id}`} className="input" type="number" step="any" inputMode="decimal"
                aria-describedby={`m${ms.id}-hint`} placeholder={prevMetric != null ? `Phase ${phase.phaseNo - 1}: ${prevMetric}` : undefined}
                value={metric} onChange={e => setMetric(e.target.value)} required />
              <span id={`m${ms.id}-hint`} className="faint small">{measure ?? 'In the measure the proposal promised to move'}</span>
            </div>
            <button className="btn btn--small" type="submit">Submit evidence</button>
          </form>
        ) : (
          <div className="phase__state">
            <Pill tone="linen">Evidence due</Pill>
            <p className="small">Waiting for the NGO to report this milestone.</p>
          </div>
        )
      )}
    </li>
  )
}
