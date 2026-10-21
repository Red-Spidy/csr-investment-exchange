import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Cloth, ClothLegend } from '../components/Cloth'
import { PageHead, Pill, Section, TableScroll, Loading } from '../components/ui'
import type { CommitmentView } from '../data/api'
import { useExchange, useQuery } from '../data/store'
import type { CommitmentStatus, FundPhase, Milestone } from '../data/types'
import { commitmentBands, shortCompany, shortTitle, sumByTone } from '../lib/bands'
import { dateShort, inr, inrCompact, timeShort } from '../lib/format'
import { TXN_LABEL, TXN_TONE } from '../lib/labels'

export function Funds() {
  const { companyId } = useExchange()
  const { data: companies } = useQuery(api => api.companies())
  const { data: commitments } = useQuery(api => api.commitments())
  const { data: ledger } = useQuery(api => api.ledger())
  const { data: audit } = useQuery(api => api.audit())

  const company = companies?.find(c => c.id === companyId)
  const mine = (commitments ?? []).filter(c => c.commitment.companyId === companyId)
  const mineIds = new Set(mine.map(c => c.commitment.id))
  const entries = [...(ledger ?? [])].filter(l => mineIds.has(l.commitmentId)).reverse()
  const auditRows = [...(audit ?? [])].filter(a =>
    (a.entity === 'commitment' && mineIds.has(a.entityId))
    || (a.entity === 'milestone' && mine.some(c => c.milestones.some(m => m.id === a.entityId)))).reverse()

  if (!company || !commitments || !ledger || !audit) return <Loading page="Funds">Loading funds</Loading>
  const name = shortCompany(company.name)

  return (
    <>
      <PageHead
        title="No milestone proof, no release."
        lead="Each commitment is cut into phases. A phase is paid only when a person verifies its milestone. Verifying flips one flag, and a trigger in the database moves the money. No model is anywhere near that path."
      />

      {mine.length === 0 ? (
        <div className="empty">
          <h3>{name} has not committed to a project yet</h3>
          <p>Once it funds a project, its phases and milestones appear here, one cloth per commitment.</p>
          <Link to="/matching" className="btn btn--turmeric">Find a project to fund</Link>
        </div>
      ) : (
        <div className="commitments">
          {mine.map(v => <CommitmentBlock key={v.commitment.id} v={v} />)}
        </div>
      )}

      <Section id="ledger" title="Ledger"
        hint="Every movement of money, oldest at the bottom. The database refuses to edit or delete a row, even by cascade.">
        {entries.length === 0 ? (
          <div className="empty"><h3>The ledger is empty</h3><p>Locking funds writes the first row.</p></div>
        ) : (
          <TableScroll label="Ledger rows">
          <table className="table ledger">
            <thead>
              <tr><th scope="col">Row</th><th scope="col">When</th><th scope="col">What happened</th><th scope="col">Note</th><th scope="col" className="r">Amount</th></tr>
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

        {auditRows.length > 0 && (
          <details className="sql-disclosure">
            <summary>Audit log ({auditRows.length})</summary>
            <TableScroll label="Audit log rows">
            <table className="table ledger">
              <thead><tr><th scope="col">When</th><th scope="col">Entity</th><th scope="col">Action</th><th scope="col">Detail</th></tr></thead>
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
          </details>
        )}
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

function CommitmentBlock({ v }: { v: CommitmentView }) {
  const bands = commitmentBands(v)
  const totals = sumByTone(bands)
  const legend = (['released', 'review', 'locked', 'held', 'returned'] as const)
    .filter(t => totals[t] > 0).map(t => ({ tone: t, value: inrCompact(totals[t]) }))
  const { status } = v.commitment

  return (
    <section className="commit" aria-labelledby={`c${v.commitment.id}`}>
      <header className="commit__head">
        <div>
          <h2 id={`c${v.commitment.id}`}><Link to={`/projects/${v.project.id}`}>{v.project.title}</Link></h2>
          <p className="muted">
            {v.ngoName}.{' '}
            {status === 'cancelled'
              ? `${v.companyName} terminated this commitment: ${inr(totals.released)} was paid and ${inr(totals.returned)} went back to its budget.`
              : `${inr(v.commitment.amount)} locked by ${v.companyName}.`}
          </p>
        </div>
        <Pill tone={COMMITMENT_PILL[status].tone}>{COMMITMENT_PILL[status].label}</Pill>
      </header>

      <Cloth bands={bands} height={64} label={`${v.project.title}: ${legend.map(l => `${l.tone} ${l.value}`).join(', ')}`} />
      <ClothLegend items={legend} />

      <ol className="phases">
        {v.phases.map(p => {
          const ms = v.milestones.find(m => m.phaseNo === p.phaseNo)!
          const before = v.phases.filter(x => x.phaseNo < p.phaseNo)
          const blocked = before.some(x => x.status !== 'released')
          return <PhaseCard key={p.id} phase={p} ms={ms} blockedBy={blocked ? before.find(x => x.status !== 'released')! : null}
            prevMetric={v.milestones.find(m => m.phaseNo === p.phaseNo - 1)?.reportedMetric ?? null} />
        })}
      </ol>

      {status === 'active' && (
        // Keyed on the held phase so a fresh failure brings its own prefilled reason.
        <EndCommitment key={v.phases.find(p => p.status === 'held')?.id ?? 0} v={v}
          unreleased={totals.locked + totals.review + totals.held} />
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
        Terminating ends the commitment for good. The {inrCompact(unreleased)} not yet released goes back to
        {' '}{company}'s budget, and what was already paid stays paid.
      </p>
      <div className="field">
        <label htmlFor={id}>Reason, written to the ledger and the audit log</label>
        <input id={id} className="input" value={reason} maxLength={500} required
          onChange={e => { setReason(e.target.value); setConfirming(false) }} />
      </div>
      {confirming ? (
        <div className="confirm confirm--danger" role="group" aria-label={`Confirm terminating ${shortTitle(v.project.title)}`}>
          <p>
            Return <strong>{inr(unreleased)}</strong> to {company} and close {shortTitle(v.project.title)}?
            The project cannot be funded again, and this cannot be undone.
          </p>
          <div className="confirm__actions">
            <button type="button" className="btn btn--danger"
              onClick={() => act('Terminate and refund', api => api.terminateCommitment(v.commitment.id, reason))}>
              Terminate and refund
            </button>
            <button type="button" className="btn btn--quiet" autoFocus onClick={() => setConfirming(false)}>Keep it</button>
          </div>
        </div>
      ) : (
        <button className="btn btn--small btn--danger" type="submit">Terminate and refund {inrCompact(unreleased)}</button>
      )}
    </form>
  )

  if (held) {
    return (
      <div className="end-box" role="group" aria-labelledby={`${id}h`}>
        <h3 id={`${id}h`}>Phase {held.phaseNo} failed verification</h3>
        <p className="small muted">
          Its {inrCompact(held.amount)} is held and will not be paid, and the phases after it cannot open. A failed
          verification cannot be undone, so this money moves only if the commitment is terminated.
        </p>
        {form}
      </div>
    )
  }
  return (
    <details className="sql-disclosure end-early">
      <summary>End this commitment early</summary>
      {form}
    </details>
  )
}

function PhaseCard({ phase, ms, blockedBy, prevMetric }: {
  phase: FundPhase; ms: Milestone; blockedBy: FundPhase | null; prevMetric: number | null
}) {
  const { act } = useExchange()
  const [metric, setMetric] = useState(String(prevMetric ?? 3))
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
            Verified by {ms.verifiedBy}. NGO reported {ms.reportedMetric}.
            {phase.releasedAt && <> Paid {dateShort(phase.releasedAt)}.</>}
          </p>
        </div>
      )}

      {phase.status === 'held' && (
        <div className="phase__state">
          <Pill tone="madder">Held</Pill>
          <p className="small">
            Verification failed. The {inrCompact(phase.amount)} stays locked and is not paid unless the commitment
            is terminated, which returns it to the company.
          </p>
        </div>
      )}

      {phase.status === 'terminated' && (
        <div className="phase__state">
          <Pill tone="linen">Refunded</Pill>
          <p className="small">
            Never paid. The commitment was terminated and the {inrCompact(phase.amount)} went back to the company's budget.
          </p>
        </div>
      )}

      {phase.status === 'locked' && ms.verification === 'submitted' && (
        <div className="phase__state">
          <Pill tone="turmeric">Evidence in</Pill>
          <p className="small">
            NGO reports {ms.reportedMetric} ({ms.evidenceUri}). A reviewer decides. Verifying releases {inrCompact(phase.amount)}.
            Failing holds it.
          </p>
          <div className="phase__actions">
            <button className="btn btn--small"
              onClick={() => act(`Verify ${label}`, api => api.verifyMilestone(ms.id))}>Verify and release</button>
            <button className="btn btn--small btn--danger"
              onClick={() => act(`Fail ${label}`, api => api.failMilestone(ms.id))}>Fail and hold</button>
          </div>
        </div>
      )}

      {phase.status === 'locked' && ms.verification === 'pending' && (
        blockedBy ? (
          <div className="phase__state">
            <Pill tone="linen">Locked</Pill>
            <p className="small">
              {blockedBy.status === 'held'
                ? `Cannot open while phase ${blockedBy.phaseNo} is held.`
                : `Opens after phase ${blockedBy.phaseNo} is verified.`}
            </p>
          </div>
        ) : (
          <form className="phase__state" onSubmit={e => {
            e.preventDefault()
            const value = Number(metric)
            if (Number.isFinite(value)) act(`Submit evidence for ${label}`, api => api.submitEvidence(ms.id, value))
          }}>
            <Pill tone="linen">Waiting for the NGO</Pill>
            <div className="field">
              <label htmlFor={`m${ms.id}`}>Result the NGO reports</label>
              <input id={`m${ms.id}`} className="input" type="number" step="any" inputMode="decimal"
                value={metric} onChange={e => setMetric(e.target.value)} required />
            </div>
            <button className="btn btn--small btn--quiet" type="submit">Submit evidence as the NGO</button>
            <p className="faint small">Submitting moves no money. Only a verification does.</p>
          </form>
        )
      )}
    </li>
  )
}
