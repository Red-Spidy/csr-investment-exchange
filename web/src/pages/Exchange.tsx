import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Cloth, ClothLegend, type Band, type Tone } from '../components/Cloth'
import { Kpis, Loading, PageHead, Pill, Section, TableScroll } from '../components/ui'
import { usePortal } from '../data/portal'
import { useExchange, useQuery } from '../data/store'
import { commitmentBands, shortTitle, sumByTone } from '../lib/bands'
import { inrCompact, pct, timeShort } from '../lib/format'
import { TXN_LABEL, TXN_TONE } from '../lib/labels'
import { openMilestone } from '../lib/milestones'

/** The company's overview: its CSR budget as cloth, what needs a decision, and its projects. */
export function Exchange() {
  const { companyId } = useExchange()
  const { to } = usePortal()
  const { data: companies } = useQuery(api => api.companies())
  const { data: commitments } = useQuery(api => api.commitments())
  const { data: ledger } = useQuery(api => api.ledger())
  const { data: rulebooks } = useQuery(api => api.rulebooks())
  const rulebook = rulebooks?.filter(r => r.companyId === companyId).sort((a, b) => b.id - a.id)[0]
  const { data: report } = useQuery(
    api => (rulebook ? api.matches(rulebook.id) : Promise.resolve(undefined)), [rulebook?.id])

  const company = companies?.find(c => c.id === companyId)
  const mine = useMemo(
    () => (commitments ?? []).filter(c => c.commitment.companyId === companyId), [commitments, companyId])

  const { bands, totals, remaining } = useMemo(() => {
    // A refunded phase is back in the unplaced budget, so it is not drawn as placed.
    const phaseBands = mine.flatMap(commitmentBands).filter(b => b.tone !== 'returned')
    const placed = phaseBands.reduce((t, b) => t + b.amount, 0)
    const left = company ? Math.max(0, company.mandatedBudget - placed) : 0
    const all: Band[] = [...phaseBands]
    if (left > 0) all.push({ key: 'free', amount: left, tone: 'free', label: 'Unplaced', hint: 'Budget not yet committed' })
    return { bands: all, totals: sumByTone(all), remaining: left }
  }, [mine, company])

  if (!company || !commitments || !ledger || !rulebooks || (rulebook && !report)) return <Loading page="Overview">Loading your overview</Loading>

  const open = mine.filter(c => c.commitment.status === 'active')
  const held = open.flatMap(c => c.phases.map(p => ({ c, p }))).filter(x => x.p.status === 'held')
  const matches = report?.ranked.slice(0, 2) ?? []
  const mineIds = new Set(mine.map(c => c.commitment.id))
  const recent = [...ledger].filter(l => mineIds.has(l.commitmentId)).reverse().slice(0, 6)

  const legend: { tone: Tone; value?: string }[] = (['released', 'review', 'locked', 'held', 'free'] as Tone[])
    .filter(t => totals[t] > 0)
    .map(t => ({ tone: t, value: inrCompact(totals[t]) }))

  const progress = (id: number) => {
    const v = mine.find(c => c.commitment.id === id)!
    if (v.commitment.status === 'completed') return 'Completed'
    if (v.commitment.status === 'cancelled') return 'Ended early'
    if (v.phases.some(p => p.status === 'held')) return 'Payment held'
    if (v.milestones.some(m => m.verification === 'submitted')) return 'Evidence with the reviewer'
    const m = openMilestone(v)
    return m ? `Phase ${m.phaseNo} in progress` : 'In progress'
  }

  return (
    <>
      <PageHead title="Overview"
        lead={`Your ${company.fy} CSR budget: ${pct(company.mandatedBudget / company.avgNetProfit)} of ${inrCompact(company.avgNetProfit)} average net profit, as Section 135 requires.`}>
        <Link to={to('/find')} className="btn btn--turmeric">Find projects</Link>
      </PageHead>

      <section className="budget" aria-labelledby="budget-h">
        <h2 id="budget-h" className="sr-only">CSR budget</h2>
        <Kpis items={[
          { label: 'CSR budget', value: inrCompact(company.mandatedBudget) },
          { label: 'Released to NGOs', value: inrCompact(totals.released) },
          { label: 'Committed, not yet released', value: inrCompact(totals.locked + totals.review + totals.held) },
          { label: 'Unplaced', value: inrCompact(remaining), tone: remaining > 0 ? 'turmeric' : undefined },
        ]} />
        <Cloth bands={bands} height={72} animate key={`${companyId}`}
          label={`${company.name} CSR budget by state: ${legend.map(l => `${l.tone} ${l.value}`).join(', ')}`} />
        <ClothLegend items={legend} />
      </section>

      <div className="two-up">
        <Section id="attention" title="Needs you now">
          <ul className="todo">
            {held.map(({ c, p }) => (
              <li key={`h${p.id}`}>
                <div>
                  <strong>Phase {p.phaseNo} failed verification</strong>
                  <p className="muted small">{shortTitle(c.project.title)}: {inrCompact(p.amount)} is held. Decide whether to end the commitment and get the unreleased money back.</p>
                </div>
                <Link className="btn btn--small btn--quiet" to={to('/funding')}>Decide</Link>
              </li>
            ))}
            {matches.map(m => (
              <li key={m.projectId}>
                <div>
                  <strong>{shortTitle(m.title)} fits your criteria</strong>
                  <p className="muted small">{m.ngoName}, {m.state}. Asks for {inrCompact(m.requestedAmount)}; fit {m.matchScore.toFixed(2)}.</p>
                </div>
                <Link className="btn btn--small btn--turmeric" to={to('/find')}>Review match</Link>
              </li>
            ))}
            {held.length === 0 && matches.length === 0 && (
              <li className="todo__empty">
                <p className="muted">Nothing needs you right now. Approved projects that fit your criteria will show up here.</p>
              </li>
            )}
          </ul>
        </Section>

        <Section id="latest" title="Recent activity">
          {recent.length === 0 ? (
            <div className="empty">
              <h3>No money has moved yet</h3>
              <p>Fund an approved project and its first entry appears here.</p>
            </div>
          ) : (
            <ul className="feed">
              {recent.map(l => (
                <li key={l.id}>
                  <Pill tone={TXN_TONE[l.type]}>{TXN_LABEL[l.type]}</Pill>
                  <span className="feed__note">{l.note}</span>
                  <strong className="num">{inrCompact(l.amount)}</strong>
                  <time className="faint small" dateTime={l.createdAt}>{timeShort(l.createdAt)}</time>
                </li>
              ))}
            </ul>
          )}
          {recent.length > 0 && <p className="feed__more"><Link to={to('/funding#ledger')} className="link-btn">Full ledger</Link></p>}
        </Section>
      </div>

      <Section id="portfolio" title="Your projects">
        {mine.length === 0 ? (
          <div className="empty">
            <h3>You have not funded a project yet</h3>
            <p>Approved projects are ranked against your criteria on Find projects.</p>
            <Link className="btn btn--small btn--turmeric" to={to('/find')}>Find projects</Link>
          </div>
        ) : (
          <TableScroll label="Your projects">
            <table className="table register">
              <thead>
                <tr>
                  <th scope="col">Project</th><th scope="col" className="r">Committed</th>
                  <th scope="col" className="r">Released</th><th scope="col">Progress</th>
                </tr>
              </thead>
              <tbody>
                {mine.map(v => {
                  const paid = v.phases.filter(p => p.status === 'released').reduce((t, p) => t + p.amount, 0)
                  return (
                    <tr key={v.commitment.id}>
                      <th scope="row">
                        <Link to={to(`/projects/${v.project.id}`)} className="register__title">{v.project.title}</Link>
                        <span className="faint small">{v.ngoName}</span>
                      </th>
                      <td className="r num">{inrCompact(v.commitment.amount)}</td>
                      <td className="r num">{inrCompact(paid)}</td>
                      <td className="small">{progress(v.commitment.id)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Section>
    </>
  )
}
