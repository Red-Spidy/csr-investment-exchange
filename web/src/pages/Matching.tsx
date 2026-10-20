import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHead, Pill, ScoreStack, Section, Sql } from '../components/ui'
import { MATCH_WEIGHTS, type MatchRow } from '../data/engine'
import { useExchange, useQuery } from '../data/store'
import { shortCompany, shortTitle } from '../lib/bands'
import { fixed, inr, inrCompact } from '../lib/format'
import { sdgName, sectorLabel, STATUS_LABEL } from '../lib/labels'

const MATCH_SQL = `SELECT * FROM fn_match_projects(:rulebook_id, 5);

-- inside the function:
  0.60 * (1 - (e.embedding <=> r.embedding))   -- cosine similarity, pgvector
+ 0.25 * impact_norm                            -- predicted impact
+ 0.15 * (1 - anomaly_score)                    -- trust in the NGO's spending
  AS match_score

WHERE p.status = 'approved'
  AND p.requested_amount BETWEEN r.min_budget AND r.max_budget
  AND (cardinality(r.preferred_states) = 0 OR p.state = ANY(r.preferred_states))
  AND (cardinality(r.target_sdgs) = 0 OR e.sdgs && r.target_sdgs)
ORDER BY match_score DESC`

export function Matching() {
  const { companyId, act } = useExchange()
  const { data: companies } = useQuery(api => api.companies())
  const { data: rulebooks } = useQuery(api => api.rulebooks())
  const company = companies?.find(c => c.id === companyId)
  const rulebook = rulebooks?.find(r => r.companyId === companyId)
  const { data: report } = useQuery(
    api => (rulebook ? api.matches(rulebook.id) : Promise.resolve(undefined)), [rulebook?.id])

  const [confirming, setConfirming] = useState<number | null>(null)
  const [done, setDone] = useState<{ title: string; amount: number } | null>(null)

  if (!company || !rulebook) return <div className="loading" aria-busy="true">Loading the rulebook</div>

  const name = shortCompany(company.name)
  const remaining = company.mandatedBudget - company.committedBudget

  async function commit(m: MatchRow) {
    const result = await act(`Commit ${inrCompact(m.requestedAmount)} to ${shortTitle(m.title)}`, api =>
      api.commitFunds({ companyId, projectId: m.projectId, amount: m.requestedAmount }))
    setConfirming(null)
    if (result.ok) setDone({ title: m.title, amount: m.requestedAmount })
  }

  return (
    <>
      <PageHead
        title={`Which approved projects fit what ${name} asked for?`}
        lead="The database compares the rulebook with every project. Hard limits remove some, then it ranks the rest by how close they are in meaning, how much impact they promise and how far their spending can be trusted."
      />

      <section className="rulebook" aria-labelledby="rb">
        <h2 id="rb" className="sr-only">{name}'s rulebook</h2>
        <blockquote className="rulebook__quote display">{rulebook.requirementText}</blockquote>
        <dl className="facts facts--wide">
          <div><dt>Focus</dt><dd>{rulebook.focusAreas.map(sectorLabel).join(', ')}</dd></div>
          <div><dt>States</dt><dd>{rulebook.preferredStates.length ? rulebook.preferredStates.join(', ') : 'Any state'}</dd></div>
          <div>
            <dt>Goals</dt>
            <dd>{rulebook.targetSdgs.map(g => `${g}. ${sdgName(g)}`).join(', ')}</dd>
          </div>
          <div><dt>Per project</dt><dd className="num">{inrCompact(rulebook.minBudget)} to {inrCompact(rulebook.maxBudget)}</dd></div>
          <div><dt>Budget left</dt><dd className="num">{inrCompact(remaining)} of {inrCompact(company.mandatedBudget)}</dd></div>
        </dl>
      </section>

      {done && (
        <div className="banner" role="status">
          <div>
            <strong>{inrCompact(done.amount)} is locked for {shortTitle(done.title)}.</strong>
            <p className="small">The phases and their milestones now exist. Money moves only as each one is verified.</p>
          </div>
          <Link to="/funds" className="btn btn--small">See the phases</Link>
          <button className="link-btn" onClick={() => setDone(null)}>Dismiss</button>
        </div>
      )}

      <Section id="ranked" title={report?.ranked.length ? 'Best fits, in order' : 'No project fits yet'}
        hint={`match score = ${MATCH_WEIGHTS.similarity.toFixed(2)} x similarity + ${MATCH_WEIGHTS.impact.toFixed(2)} x predicted impact + ${MATCH_WEIGHTS.trust.toFixed(2)} x (1 - fraud score)`}>
        {report && report.ranked.length === 0 && (
          <div className="empty">
            <h3>Nothing passes {name}'s limits</h3>
            <p>Every project is either not approved or outside the budget, state or goals in the rulebook. The list below says why for each one.</p>
          </div>
        )}
        <ol className="matches">
          {report?.ranked.map((m, i) => (
            <li key={m.projectId} className="match">
              <span className="match__rank display" aria-label={`Rank ${i + 1}`}>{i + 1}</span>
              <div className="match__body">
                <div className="match__top">
                  <div>
                    <h3><Link to={`/projects/${m.projectId}`}>{m.title}</Link></h3>
                    <p className="muted small">{m.ngoName}, {m.state}. Asks for {inr(m.requestedAmount)}.</p>
                  </div>
                  <p className="match__score display" aria-label={`Match score ${m.matchScore.toFixed(2)}`}>
                    {m.matchScore.toFixed(2)}
                  </p>
                </div>

                <ScoreStack
                  caption={`Match score ${m.matchScore.toFixed(2)} built from similarity, impact and trust`}
                  total={Math.max(0, m.matchScore)}
                  segments={[
                    { key: 's', label: 'Closeness in meaning', value: m.contributions.similarity, tone: 'indigo', note: `${fixed(m.similarity, 2)} similar` },
                    { key: 'i', label: 'Predicted impact', value: m.contributions.impact, tone: 'turmeric', note: `${m.impactNorm.toFixed(2)}` },
                    { key: 't', label: 'Trust', value: m.contributions.trust, tone: 'neem', note: `fraud ${m.fraudScore.toFixed(2)}` },
                  ]}
                />

                {m.similarity < 0.3 && (
                  <p className="note small">
                    This only passed the limits because it shares goal {m.sharedSdgs.join(' and ')}. Its text similarity is
                    {' '}{fixed(m.similarity, 2)}, so it ranks low.
                  </p>
                )}

                {confirming === m.projectId ? (
                  <div className="confirm" role="group" aria-label={`Confirm funding ${shortTitle(m.title)}`}>
                    <p>
                      Lock <strong>{inr(m.requestedAmount)}</strong> for this project, split into the phases it asked for.
                      {' '}{name}'s unplaced budget goes from {inrCompact(remaining)} to {inrCompact(remaining - m.requestedAmount)}.
                      No phase is paid until its milestone is verified.
                    </p>
                    {m.requestedAmount > remaining && (
                      <p className="bad small">This is more than the budget left. The database will refuse it.</p>
                    )}
                    <div className="confirm__actions">
                      <button className="btn" onClick={() => commit(m)}>Lock {inrCompact(m.requestedAmount)}</button>
                      <button className="btn btn--quiet" onClick={() => setConfirming(null)}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="match__actions">
                    <button className="btn btn--turmeric" onClick={() => setConfirming(m.projectId)}>
                      Fund this project
                    </button>
                    <Link to={`/projects/${m.projectId}`} className="btn btn--quiet">Read the scorecard</Link>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      </Section>

      {report && report.excluded.length > 0 && (
        <Section id="excluded" title="Left out, and why"
          hint="Every project that did not make the list, with the rule that removed it.">
          <table className="table excluded">
            <thead><tr><th scope="col">Project</th><th scope="col">Why it is out</th></tr></thead>
            <tbody>
              {report.excluded.map(e => (
                <tr key={e.projectId}>
                  <th scope="row">
                    <Link to={`/projects/${e.projectId}`}>{shortTitle(e.title)}</Link>
                    <span className="faint small">{e.ngoName}, {inrCompact(e.requestedAmount)}</span>
                  </th>
                  <td>
                    <ul className="plain">
                      {e.reasons.map(r => <li key={r}>{r}</li>)}
                    </ul>
                    {e.status !== 'approved' && <Pill tone={e.status === 'flagged' ? 'madder' : 'indigo'}>{STATUS_LABEL[e.status]}</Pill>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      <details className="sql-disclosure">
        <summary>Show the SQL behind this ranking</summary>
        <Sql label="db/migrations/005_views_windows.sql">{MATCH_SQL}</Sql>
      </details>
    </>
  )
}
