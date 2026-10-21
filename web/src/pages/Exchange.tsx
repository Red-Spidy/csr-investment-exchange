import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Cloth, ClothLegend, type Band, type Tone } from '../components/Cloth'
import { PageHead, Pill, Section, Loading } from '../components/ui'
import { useExchange, useQuery } from '../data/store'
import type { ProjectStatus } from '../data/types'
import { commitmentBands, shortCompany, shortTitle, sumByTone } from '../lib/bands'
import { inrCompact, pct, timeShort } from '../lib/format'
import { TXN_LABEL, TXN_TONE } from '../lib/labels'

const STAGES: { title: string; hint: string; statuses: ProjectStatus[] }[] = [
  { title: 'Being scored', hint: 'Proposal read, impact and fraud scored', statuses: ['pending', 'scoring'] },
  { title: 'Approved', hint: 'Cleared to be matched with a company', statuses: ['approved'] },
  { title: 'Funded', hint: 'Money locked, phases releasing', statuses: ['matched', 'active'] },
  { title: 'Closed', hint: 'Every phase released, or ended early', statuses: ['closed', 'terminated'] },
]

export function Exchange() {
  const { companyId } = useExchange()
  const { data: companies } = useQuery(api => api.companies())
  const { data: commitments } = useQuery(api => api.commitments())
  const { data: scorecard } = useQuery(api => api.scorecard())
  const { data: ledger } = useQuery(api => api.ledger())
  const { data: rulebooks } = useQuery(api => api.rulebooks())
  const rulebook = rulebooks?.find(r => r.companyId === companyId)
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

  if (!company || !commitments || !scorecard || !ledger || !rulebooks || (rulebook && !report)) return <Loading page="Exchange">Loading the exchange</Loading>

  const name = shortCompany(company.name)
  const open = mine.filter(c => c.commitment.status === 'active')
  const awaiting = open.flatMap(c => c.milestones.map(m => ({ c, m }))).filter(x => x.m.verification === 'submitted')
  const held = open.flatMap(c => c.phases.map(p => ({ c, p }))).filter(x => x.p.status === 'held')
  const topMatch = report?.ranked[0]
  const mineIds = new Set(mine.map(c => c.commitment.id))
  const recent = [...(ledger ?? [])].filter(l => mineIds.has(l.commitmentId)).reverse().slice(0, 5)
  const stageProjects = (statuses: ProjectStatus[]) => (scorecard ?? []).filter(p => statuses.includes(p.status))
  // A funded project is flagged when a milestone fails; that shows under "needs next" instead.
  const flagged = (scorecard ?? []).filter(p => p.status === 'flagged' && p.commitmentId === null)

  const legend: { tone: Tone; value?: string }[] = (['released', 'review', 'locked', 'held', 'free'] as Tone[])
    .filter(t => totals[t] > 0)
    .map(t => ({ tone: t, value: inrCompact(totals[t]) }))

  return (
    <>
      <PageHead
        title={remaining > 0
          ? `${inrCompact(remaining)} of ${name}'s CSR budget is still unplaced.`
          : `All of ${name}'s CSR budget is placed.`}
        lead={`The ${company.fy} mandate is ${inrCompact(company.mandatedBudget)}, which is ${pct(company.mandatedBudget / company.avgNetProfit)} of ${inrCompact(company.avgNetProfit)} average net profit, as Section 135 requires.`}
      />

      <div className="hero-cloth">
        <Cloth bands={bands} height={96} animate key={`${companyId}`}
          label={`${company.name} CSR budget by state: ${legend.map(l => `${l.tone} ${l.value}`).join(', ')}`} />
        <ClothLegend items={legend} />
      </div>

      <Section id="pipeline" title="Where every proposal stands"
        hint="A proposal is read, scored, approved, matched, then funded in phases. Nothing skips a stage.">
        <div className="pipeline">
          {STAGES.map((stage, i) => {
            const items = stageProjects(stage.statuses)
            return (
              <div key={stage.title} className="stage" data-empty={items.length === 0 || undefined}>
                <div className="stage__head">
                  <span className="stage__count" aria-hidden="true">{items.length}</span>
                  <div>
                    <h3>{stage.title}</h3>
                    <p className="small faint">{stage.hint}</p>
                  </div>
                </div>
                {items.length === 0 ? (
                  <p className="stage__none small faint">{i === 0 ? 'Nothing waiting to be scored.' : 'Nothing here yet.'}</p>
                ) : (
                  <ul className="stage__list">
                    {items.map(p => (
                      <li key={p.projectId}>
                        <Link to={`/projects/${p.projectId}`} className="chip">
                          <span className="chip__title">{shortTitle(p.title)}</span>
                          <span className="chip__meta">{p.ngoName}, {inrCompact(p.requestedAmount)}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </div>

        {flagged.length > 0 && (
          <div className="held-back">
            <h3>Held back for review</h3>
            <p className="small muted">These were scored but not cleared. They cannot be matched or funded.</p>
            <ul className="held-back__list">
              {flagged.map(p => (
                <li key={p.projectId}>
                  <Link to={`/projects/${p.projectId}`} className="chip chip--flag">
                    <span className="chip__title">{shortTitle(p.title)}</span>
                    <span className="chip__meta">Grade {p.grade}, {p.ngoName}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      <div className="two-up">
        <Section id="attention" title={`What needs ${name} next`}>
          <ul className="todo">
            {awaiting.map(({ c, m }) => (
              <li key={m.id}>
                <div>
                  <strong>Phase {m.phaseNo} evidence is in</strong>
                  <p className="muted small">{shortTitle(c.project.title)}. A reviewer has to verify or fail it before any money moves.</p>
                </div>
                <Link className="btn btn--small" to="/funds">Review</Link>
              </li>
            ))}
            {held.map(({ c, p }) => (
              <li key={`h${p.id}`}>
                <div>
                  <strong>Phase {p.phaseNo} is held</strong>
                  <p className="muted small">{shortTitle(c.project.title)}. {inrCompact(p.amount)} stays locked. Ending the commitment returns the unreleased money to {name}.</p>
                </div>
                <Link className="btn btn--small btn--quiet" to="/funds">Decide</Link>
              </li>
            ))}
            {topMatch && (
              <li>
                <div>
                  <strong>{shortTitle(topMatch.title)} fits your rulebook</strong>
                  <p className="muted small">
                    Match score {topMatch.matchScore.toFixed(2)} for {inrCompact(topMatch.requestedAmount)} from {topMatch.ngoName}.
                  </p>
                </div>
                <Link className="btn btn--small btn--turmeric" to="/matching">See match</Link>
              </li>
            )}
            {awaiting.length === 0 && held.length === 0 && !topMatch && (
              <li className="todo__empty">
                <p className="muted">Nothing needs {name} right now. Approved proposals that fit its rulebook will show up here.</p>
              </li>
            )}
          </ul>
        </Section>

        <Section id="latest" title="Latest ledger entries"
          hint="The ledger only ever grows. Rows are never edited or deleted.">
          {recent.length === 0 ? (
            <div className="empty">
              <h3>No money has moved yet</h3>
              <p>Commit funds to an approved project and the first entry appears here.</p>
              <Link className="btn btn--small" to="/matching">Find a project</Link>
            </div>
          ) : (
            <ul className="feed">
              {recent.map(l => (
                <li key={l.id}>
                  <Pill tone={TXN_TONE[l.type]}>
                    {TXN_LABEL[l.type]}
                  </Pill>
                  <span className="feed__note">{l.note}</span>
                  <strong className="num">{inrCompact(l.amount)}</strong>
                  <time className="faint small" dateTime={l.createdAt}>{timeShort(l.createdAt)}</time>
                </li>
              ))}
            </ul>
          )}
          <p className="feed__more"><Link to="/funds#ledger" className="link-btn">Open the full ledger</Link></p>
        </Section>
      </div>
    </>
  )
}
