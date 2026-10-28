import { Link } from 'react-router-dom'
import { Grade, Kpis, Loading, PageHead, RatingBadge, Section, TableScroll, raterName } from '../components/ui'
import type { ScorecardRow } from '../data/engine'
import { usePortal } from '../data/portal'
import { useExchange, useQuery } from '../data/store'
import { shortTitle } from '../lib/bands'
import { dateShort, inrCompact } from '../lib/format'

/** The main reason the scoring held a project back, in a few words. */
function heldBecause(r: ScorecardRow): string {
  if (r.isAnomaly) return 'Unusual spending history'
  if (r.grade === 'C' || r.grade === 'D') return `Grade ${r.grade}, below automatic approval`
  return 'No measurable target'
}

export function ReviewQueue() {
  const { to } = usePortal()
  const { act } = useExchange()
  const { data: rows } = useQuery(api => api.scorecard())
  const { data: commitments } = useQuery(api => api.commitments())
  if (!rows || !commitments) return <Loading page="Review queue">Loading the queue</Loading>

  const decide = rows.filter(r => r.status === 'flagged' && r.commitmentId === null)
  const evidence = commitments.flatMap(v => v.milestones.filter(m => m.verification === 'submitted').map(m => ({
    v, m, phase: v.phases.find(p => p.phaseNo === m.phaseNo)!,
  })))
  const active = commitments.filter(c => c.commitment.status === 'active')
  const locked = active.flatMap(c => c.phases).filter(p => p.status === 'locked').reduce((t, p) => t + p.amount, 0)

  return (
    <>
      <PageHead title="Review queue" lead="Proposals the scoring held back, and milestone evidence waiting to be verified." />

      <Kpis items={[
        { label: 'Proposals to decide', value: decide.length, tone: decide.length ? 'turmeric' : undefined },
        { label: 'Evidence to verify', value: evidence.length, tone: evidence.length ? 'turmeric' : undefined },
        { label: 'Funded projects', value: active.length },
        { label: 'Waiting on milestones', value: inrCompact(locked) },
      ]} />

      <Section id="decide" title="Proposals to decide" hint="Held back by the scoring. Nothing is rejected without a person.">
        {decide.length === 0 ? (
          <div className="empty"><h3>No proposals waiting</h3><p>Proposals the scoring holds back appear here.</p></div>
        ) : (
          <TableScroll label="Proposals to decide">
            <table className="table register">
              <thead>
                <tr>
                  <th scope="col">Project</th><th scope="col">Grade</th><th scope="col">Held back for</th>
                  <th scope="col" className="r">Requested</th><th scope="col"><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {decide.map(r => (
                  <tr key={r.projectId}>
                    <th scope="row">
                      <Link to={to(`/projects/${r.projectId}`)} className="register__title">{r.title}</Link>
                      <span className="faint small">{r.ngoName}{r.state ? `, ${r.state}` : ''}</span>
                    </th>
                    <td><Grade grade={r.grade} /></td>
                    <td>{heldBecause(r)}</td>
                    <td className="r num">{inrCompact(r.requestedAmount)}</td>
                    <td className="r"><Link className="btn btn--small btn--quiet" to={to(`/projects/${r.projectId}`)}>Review</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Section>

      <Section id="verify" title="Evidence to verify"
        hint="Read the NGO's words and the rating, then decide. Verifying releases that phase's money; failing holds it.">
        {evidence.length === 0 ? (
          <div className="empty"><h3>No evidence waiting</h3><p>When an NGO reports a milestone, it appears here.</p></div>
        ) : (
          <TableScroll label="Evidence to verify">
            <table className="table register">
              <thead>
                <tr>
                  <th scope="col">Project</th><th scope="col">Milestone, in the NGO's words</th><th scope="col">Rating</th>
                  <th scope="col" className="r">Result</th><th scope="col" className="r">Releases</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {evidence.map(({ v, m, phase }) => (
                  <tr key={m.id}>
                    <th scope="row">
                      <Link to={to(`/projects/${v.project.id}`)} className="register__title">{shortTitle(v.project.title)}</Link>
                      <span className="faint small">{v.ngoName}, funded by {v.companyName}</span>
                    </th>
                    <td className="evidence-words">
                      Phase {m.phaseNo}: {m.description}
                      <span className="faint small block">{m.reportedAt ? `Reported ${dateShort(m.reportedAt)}` : ''}</span>
                      {m.updateText
                        ? <span className="small block quoted">“{m.updateText}”</span>
                        : <span className="faint small block">No words given with this evidence.</span>}
                    </td>
                    <td>
                      <RatingBadge rating={m.rating} />
                      {m.ratingReason && <span className="small block">{m.ratingReason}</span>}
                      {m.ratingFlags.map(f => <span key={f} className="small block bad">{f}</span>)}
                      {m.ratedBy && <span className="faint small block">By {raterName(m.ratedBy)}</span>}
                    </td>
                    <td className="r num">{m.reportedMetric}</td>
                    <td className="r num">{inrCompact(phase.amount)}</td>
                    <td className="r">
                      <div className="row-actions">
                        <button className="btn btn--small" onClick={() => act(`Phase ${m.phaseNo} verified`, api => api.verifyMilestone(m.id))}>Verify</button>
                        <button className="btn btn--small btn--danger" onClick={() => act(`Phase ${m.phaseNo} failed`, api => api.failMilestone(m.id))}>Fail</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Section>
    </>
  )
}
