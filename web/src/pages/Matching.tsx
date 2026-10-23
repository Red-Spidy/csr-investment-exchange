import { useState } from 'react'
import { Link } from 'react-router-dom'
import { HowItWorks, PageHead, ScoreStack, Section, Sql, StatusPill, TableScroll, Loading } from '../components/ui'
import type { Sector } from '../data/api'
import { MATCH_WEIGHTS, type MatchRow } from '../data/engine'
import { usePortal } from '../data/portal'
import { useExchange, useQuery } from '../data/store'
import { shortTitle } from '../lib/bands'
import { fixed, inr, inrCompact } from '../lib/format'
import { sdgName, sectorLabel } from '../lib/labels'

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
  const { to } = usePortal()
  const { data: companies } = useQuery(api => api.companies())
  const { data: rulebooks } = useQuery(api => api.rulebooks())
  const company = companies?.find(c => c.id === companyId)
  // The newest rulebook is the company's current requirement.
  const rulebook = rulebooks?.filter(r => r.companyId === companyId).sort((a, b) => b.id - a.id)[0]
  const { data: report } = useQuery(
    api => (rulebook ? api.matches(rulebook.id) : Promise.resolve(undefined)), [rulebook?.id])

  const [confirming, setConfirming] = useState<number | null>(null)
  const [done, setDone] = useState<{ title: string; amount: number } | null>(null)
  const [writing, setWriting] = useState(false)

  if (!company || !rulebook || !report) return <Loading page="Find projects">Loading matches</Loading>

  const remaining = company.mandatedBudget - company.committedBudget

  async function commit(m: MatchRow) {
    const result = await act(`${inrCompact(m.requestedAmount)} committed to ${shortTitle(m.title)}`, api =>
      api.commitFunds({ companyId, projectId: m.projectId, amount: m.requestedAmount }))
    setConfirming(null)
    if (result.ok) setDone({ title: m.title, amount: m.requestedAmount })
  }

  return (
    <>
      <PageHead title="Find projects" lead="Approved projects ranked against your funding criteria.">
        <button className="btn btn--quiet" aria-expanded={writing} onClick={() => setWriting(v => !v)}>
          {writing ? 'Cancel' : 'Edit criteria'}
        </button>
      </PageHead>

      {writing && <RulebookForm companyId={companyId} onSaved={() => setWriting(false)} />}

      <section className="rulebook" aria-labelledby="rb">
        <h2 id="rb" className="rulebook__label">Your criteria</h2>
        <blockquote className="rulebook__quote">{rulebook.requirementText}</blockquote>
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
            <strong>{inrCompact(done.amount)} committed to {shortTitle(done.title)}.</strong>
            <p className="small">Each phase is paid to the NGO once its milestone is verified.</p>
          </div>
          <Link to={to('/funding')} className="btn btn--small">View funding</Link>
          <button className="link-btn" onClick={() => setDone(null)}>Dismiss</button>
        </div>
      )}

      <Section id="ranked" title={report?.ranked.length ? `${report.ranked.length} ${report.ranked.length === 1 ? 'match' : 'matches'}` : 'No matches yet'}
        hint={report?.ranked.length ? 'Best fit first' : undefined}>
        {report && report.ranked.length === 0 && (
          <div className="empty">
            <h3>No approved project meets your criteria</h3>
            <p>Every project is either not yet approved or outside your budget, states or goals. The list below says why for each.</p>
          </div>
        )}
        <ol className="matches">
          {report?.ranked.map((m, i) => (
            <li key={m.projectId} className="match">
              <span className="match__rank display" aria-label={`Rank ${i + 1}`}>{i + 1}</span>
              <div className="match__body">
                <div className="match__top">
                  <div>
                    <h3><Link to={to(`/projects/${m.projectId}`)}>{m.title}</Link></h3>
                    <p className="muted small">{m.ngoName}, {m.state}. Asks for {inr(m.requestedAmount)}.</p>
                  </div>
                  <p className="match__score display" aria-label={`Fit score ${m.matchScore.toFixed(2)}`}>
                    {m.matchScore.toFixed(2)}
                  </p>
                </div>

                <ScoreStack
                  caption={`Fit score ${m.matchScore.toFixed(2)} built from similarity, impact and trust`}
                  total={Math.max(0, m.matchScore)}
                  segments={[
                    { key: 's', label: 'Fits your criteria', value: m.contributions.similarity, tone: 'indigo', note: `${fixed(m.similarity, 2)} similar` },
                    { key: 'i', label: 'Expected impact', value: m.contributions.impact, tone: 'turmeric', note: `${m.impactNorm.toFixed(2)}` },
                    { key: 't', label: 'Spending record', value: m.contributions.trust, tone: 'neem', note: `risk ${m.fraudScore.toFixed(2)}` },
                  ]}
                />

                {m.similarity < 0.3 && (
                  <p className="note small">
                    Included only because it shares goal {m.sharedSdgs.join(' and ')} with your criteria. The description is a
                    weak fit ({fixed(m.similarity, 2)}), so it ranks low.
                  </p>
                )}

                {confirming === m.projectId ? (
                  <div className="confirm" role="group" aria-label={`Confirm funding ${shortTitle(m.title)}`}>
                    <p>
                      Commit <strong>{inr(m.requestedAmount)}</strong> to this project, paid in the phases it asked for.
                      Your unplaced budget goes from {inrCompact(remaining)} to {inrCompact(remaining - m.requestedAmount)}.
                      Each phase is paid only after its milestone is verified.
                    </p>
                    {m.requestedAmount > remaining && (
                      <p className="bad small">This is more than your remaining budget, so it will be refused.</p>
                    )}
                    <div className="confirm__actions">
                      <button className="btn btn--turmeric" onClick={() => commit(m)}>Commit {inrCompact(m.requestedAmount)}</button>
                      <button className="btn btn--quiet" onClick={() => setConfirming(null)}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="match__actions">
                    <button className="btn btn--turmeric" onClick={() => setConfirming(m.projectId)}>
                      Fund this project
                    </button>
                    <Link to={to(`/projects/${m.projectId}`)} className="btn btn--quiet">View project</Link>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      </Section>

      {report && report.excluded.length > 0 && (
        <Section id="excluded" title="Not eligible" hint="Projects outside your criteria, and the reason for each">
          <TableScroll label="Left-out projects and their reasons">
          <table className="table register excluded">
            <thead><tr><th scope="col">Project</th><th scope="col">Reason</th></tr></thead>
            <tbody>
              {report.excluded.map(e => (
                <tr key={e.projectId}>
                  <th scope="row">
                    <Link to={to(`/projects/${e.projectId}`)}>{shortTitle(e.title)}</Link>
                    <span className="faint small">{e.ngoName}, {inrCompact(e.requestedAmount)}</span>
                  </th>
                  <td>
                    <ul className="plain">
                      {e.reasons.map(r => <li key={r}>{r}</li>)}
                    </ul>
                    {e.status !== 'approved' && <StatusPill status={e.status} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableScroll>
        </Section>
      )}

      <HowItWorks title="How projects are ranked">
        <p>
          Postgres filters out projects that are not approved or fall outside your budget, states or goals. It ranks the
          rest by fit score = {MATCH_WEIGHTS.similarity.toFixed(2)} x how closely the proposal matches your criteria in meaning
          (pgvector cosine similarity) + {MATCH_WEIGHTS.impact.toFixed(2)} x expected impact + {MATCH_WEIGHTS.trust.toFixed(2)} x
          the NGO's spending record. Committing is one database transaction: the money is locked and the phases and
          milestones are created together.
        </p>
        <Sql label="db/migrations/005_views_windows.sql">{MATCH_SQL}</Sql>
      </HowItWorks>
    </>
  )
}

// ---------------------------------------------------------------- new rulebook

const SECTORS: Sector[] = ['education', 'healthcare', 'water_sanitation', 'environment', 'livelihood']

function RulebookForm({ companyId, onSaved }: { companyId: number; onSaved: () => void }) {
  const { act, source } = useExchange()
  const [text, setText] = useState('')
  const [focus, setFocus] = useState<Sector[]>([])
  const [states, setStates] = useState('')
  const [sdgs, setSdgs] = useState('')
  const [min, setMin] = useState('0')
  const [max, setMax] = useState('')
  const list = (v: string) => v.split(',').map(x => x.trim()).filter(Boolean)
  const sdgList = list(sdgs).map(Number)
  const badSdg = sdgList.some(n => !Number.isInteger(n) || n < 1 || n > 17)

  return (
    <Section id="new-rulebook" title="New funding criteria"
      hint={source === 'live'
        ? 'Your matches update as soon as you save.'
        : 'Saving criteria needs the server, which is not reachable.'}>
      <form className="proposal-form" onSubmit={async e => {
        e.preventDefault()
        if (badSdg) return
        const out = await act('Criteria saved', api => api.createRulebook({
          companyId, requirementText: text.trim(), focusAreas: focus, preferredStates: list(states),
          targetSdgs: sdgList, minBudget: Number(min) || 0, maxBudget: Number(max),
        }))
        if (out.ok) onSaved()
      }}>
        <div className="field proposal-form__text">
          <label htmlFor="rb-text">What you want to fund</label>
          <textarea id="rb-text" className="input" required minLength={10} maxLength={2000} rows={3}
            placeholder="e.g. Girls' secondary education in rural Bihar, with a clear attendance target."
            value={text} onChange={e => setText(e.target.value)} />
        </div>
        <fieldset className="field proposal-form__text">
          <legend>Focus areas</legend>
          <div className="filters">
            {SECTORS.map(s => (
              <label key={s} className="filter">
                <input type="checkbox" checked={focus.includes(s)}
                  onChange={e => setFocus(f => e.target.checked ? [...f, s] : f.filter(x => x !== s))} /> {sectorLabel(s)}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="field">
          <label htmlFor="rb-states">Preferred states, comma-separated</label>
          <input id="rb-states" className="input" placeholder="Any state" value={states} onChange={e => setStates(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rb-sdgs">Development goals (SDG numbers), comma-separated</label>
          <input id="rb-sdgs" className="input" placeholder="e.g. 4, 5" value={sdgs} aria-invalid={badSdg || undefined}
            onChange={e => setSdgs(e.target.value)} />
          {badSdg && <span className="bad small">SDGs are whole numbers from 1 to 17.</span>}
        </div>
        <div className="field">
          <label htmlFor="rb-min">Smallest project (₹)</label>
          <input id="rb-min" className="input" type="number" min={0} step={1} value={min} onChange={e => setMin(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rb-max">Largest project (₹)</label>
          <input id="rb-max" className="input" type="number" required min={1} step={1} value={max} onChange={e => setMax(e.target.value)} />
        </div>
        <div className="proposal-form__actions">
          <button className="btn" type="submit" disabled={badSdg}>Save criteria</button>
        </div>
      </form>
    </Section>
  )
}

