import { Link } from 'react-router-dom'
import { Kpis, Loading, PageHead, Section, StatusPill, TableScroll } from '../../components/ui'
import { usePortal } from '../../data/portal'
import { useQuery } from '../../data/store'
import { shortTitle } from '../../lib/bands'
import { dateShort, inrCompact } from '../../lib/format'
import { openMilestone } from '../../lib/milestones'

export function NgoHome() {
  const { ngoId, to } = usePortal()
  const { data: rows } = useQuery(api => api.scorecard())
  const { data: commitments } = useQuery(api => api.commitments())
  if (!rows || !commitments) return <Loading page="My projects">Loading your projects</Loading>

  const mine = rows.filter(r => r.ngoId === ngoId).sort((a, b) => b.projectId - a.projectId)
  const funded = commitments.filter(c => c.project.ngoId === ngoId)
  const committed = mine.reduce((t, r) => t + r.committedAmount, 0)
  const released = mine.reduce((t, r) => t + r.releasedAmount, 0)
  const locked = mine.reduce((t, r) => t + r.lockedAmount, 0)

  const due = funded.map(v => ({ v, m: openMilestone(v) })).filter(x => x.m?.verification === 'pending')
  const waiting = funded.flatMap(v => v.milestones.filter(m => m.verification === 'submitted').map(m => ({ v, m })))
  const held = funded.filter(v => v.commitment.status === 'active')
    .flatMap(v => v.phases.filter(p => p.status === 'held').map(p => ({ v, p })))
  const inReview = mine.filter(r => r.status === 'flagged' && r.commitmentId === null)

  const nextStep = (projectId: number, status: string) => {
    const v = funded.find(c => c.project.id === projectId && c.commitment.status === 'active')
    if (v) {
      const m = openMilestone(v)
      if (m?.verification === 'pending') return `Evidence due for phase ${m.phaseNo}`
      if (v.milestones.some(x => x.verification === 'submitted')) return 'Evidence with the reviewer'
      if (v.phases.some(p => p.status === 'held')) return 'Payment held'
    }
    if (status === 'flagged') return 'With the reviewer'
    if (status === 'approved') return 'Open to companies'
    if (status === 'closed') return 'Completed'
    return ''
  }

  return (
    <>
      <PageHead title="My projects" lead="Your proposals, the funding they have received and the milestones still to report.">
        <Link to={to('/new')} className="btn">New proposal</Link>
      </PageHead>

      <Kpis items={[
        { label: 'Proposals', value: mine.length },
        { label: 'Funding committed', value: inrCompact(committed) },
        { label: 'Received', value: inrCompact(released) },
        { label: 'Waiting on milestones', value: inrCompact(locked) },
      ]} />

      <Section id="todo" title="Needs you now">
        <ul className="todo">
          {due.map(({ v, m }) => (
            <li key={m!.id}>
              <div>
                <strong>Submit evidence for phase {m!.phaseNo}</strong>
                <p className="muted small">{shortTitle(v.project.title)}: {m!.description}, due {dateShort(m!.dueDate)}.</p>
              </div>
              <Link className="btn btn--small" to={to(`/projects/${v.project.id}#funding`)}>Submit evidence</Link>
            </li>
          ))}
          {held.map(({ v, p }) => (
            <li key={`h${p.id}`}>
              <div>
                <strong>Phase {p.phaseNo} failed verification</strong>
                <p className="muted small">{shortTitle(v.project.title)}: the {inrCompact(p.amount)} for this phase is held. {v.companyName} decides what happens next.</p>
              </div>
              <Link className="btn btn--small btn--quiet" to={to(`/projects/${v.project.id}`)}>View</Link>
            </li>
          ))}
          {due.length === 0 && held.length === 0 && (
            <li className="todo__empty">
              <p className="muted">
                Nothing needs you right now.
                {waiting.length > 0 && ` ${waiting.length} milestone ${waiting.length === 1 ? 'report is' : 'reports are'} with the reviewer.`}
                {inReview.length > 0 && ` ${inReview.length} ${inReview.length === 1 ? 'proposal is' : 'proposals are'} being reviewed.`}
              </p>
            </li>
          )}
        </ul>
      </Section>

      <Section id="projects" title="Projects">
        {mine.length === 0 ? (
          <div className="empty">
            <h3>No proposals yet</h3>
            <p>Submit your first proposal. It is scored in a few seconds and companies can fund it once approved.</p>
            <Link to={to('/new')} className="btn">New proposal</Link>
          </div>
        ) : (
          <TableScroll label="Your projects">
            <table className="table register">
              <thead>
                <tr>
                  <th scope="col">Project</th><th scope="col">Status</th><th scope="col" className="r">Requested</th>
                  <th scope="col" className="r">Received</th><th scope="col">Next step</th>
                </tr>
              </thead>
              <tbody>
                {mine.map(r => (
                  <tr key={r.projectId}>
                    <th scope="row">
                      <Link to={to(`/projects/${r.projectId}`)} className="register__title">{r.title}</Link>
                      <span className="faint small">
                        {funded.find(c => c.project.id === r.projectId)?.companyName ?? (r.state ?? '')}
                      </span>
                    </th>
                    <td><StatusPill status={r.status} held={r.heldAmount > 0} /></td>
                    <td className="r num">{inrCompact(r.requestedAmount)}</td>
                    <td className="r num">{r.commitmentId ? inrCompact(r.releasedAmount) : <span className="faint">None</span>}</td>
                    <td className="small">{nextStep(r.projectId, r.status)}</td>
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
