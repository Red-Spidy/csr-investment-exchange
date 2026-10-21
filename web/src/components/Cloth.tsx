import { inrCompact } from '../lib/format'

/**
 * The signature visual: money drawn as cloth. Width is rupees. A locked phase
 * is undyed linen, a released phase is dyed indigo, a phase waiting on a
 * reviewer is in the turmeric vat, a held phase is crosshatched in madder, and
 * budget not yet placed is an empty loom. A phase refunded when its commitment was
 * terminated is an empty loom again: the money went back to the company.
 */
export type Tone = 'released' | 'locked' | 'review' | 'held' | 'free' | 'returned'

export interface Band {
  key: string | number
  amount: number
  tone: Tone
  label: string
  sub?: string
  /** Tooltip text; defaults to the label and amount. */
  hint?: string
}

export const TONE_NAME: Record<Tone, string> = {
  released: 'Released',
  locked: 'Locked',
  review: 'Awaiting review',
  held: 'Held',
  free: 'Unplaced',
  returned: 'Refunded',
}

interface ClothProps {
  bands: Band[]
  height?: number
  /** Weave the cloth in once on mount. Use for one hero only. */
  animate?: boolean
  label: string
}

export function Cloth({ bands, height = 72, animate = false, label }: ClothProps) {
  const total = bands.reduce((t, b) => t + b.amount, 0) || 1
  return (
    <figure className="cloth" data-animate={animate || undefined} style={{ ['--h' as string]: `${height}px` }}>
      <div className="cloth__weave" role="img" aria-label={label}>
        {bands.map(b => {
          const share = b.amount / total
          return (
            <div
              key={b.key}
              className="band weave"
              data-tone={b.tone}
              style={{ flexGrow: b.amount }}
              title={`${b.hint ?? b.label}: ${inrCompact(b.amount)}, ${TONE_NAME[b.tone].toLowerCase()}`}
            >
              {share >= 0.07 && (
                <span className="band__label">
                  <strong>{b.label}</strong>
                  <span>{b.sub ?? inrCompact(b.amount)}</span>
                </span>
              )}
            </div>
          )
        })}
      </div>
    </figure>
  )
}

export function ClothLegend({ items }: { items: { tone: Tone; value?: string }[] }) {
  return (
    <ul className="legend">
      {items.map(i => (
        <li key={i.tone}>
          <span className="swatch weave" data-tone={i.tone} aria-hidden="true" />
          <span>{TONE_NAME[i.tone]}</span>
          {i.value && <strong className="num">{i.value}</strong>}
        </li>
      ))}
    </ul>
  )
}
