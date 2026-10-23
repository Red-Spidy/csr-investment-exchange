// The matcher explains each left-out project in the database's terms ("Status is flagged").
// A company reads them next to status labels like "In review", so they are reworded here.

const NOT_APPROVED: Record<string, string> = {
  pending: 'Not scored yet.',
  scoring: 'Not scored yet.',
  flagged: 'Not approved yet: it is with the reviewer.',
  rejected: 'Rejected by the reviewer.',
  matched: 'Already funded.',
  active: 'Already funded.',
  closed: 'Completed.',
  terminated: 'Its funding was ended.',
}

const RULES: [RegExp, (...m: string[]) => string][] = [
  [/^Status is (\w+); only approved projects can be matched\.$/, s => NOT_APPROVED[s] ?? `Not approved (${s}).`],
  [/^(.+) is not one of (.+)\.$/, (state, states) => `${state} is outside your states (${states}).`],
  [/^No overlap with the target (SDGs?) \((.+)\)\.$/, (sdg, list) => `Serves none of your development goals (${sdg} ${list}).`],
  [/^Asks for (.+), outside the (.+) range\.$/, (asks, range) => `Asks for ${asks}, outside your ${range} per project.`],
]

export function plainReason(reason: string): string {
  for (const [pattern, say] of RULES) {
    const m = reason.match(pattern)
    if (m) return say(...m.slice(1))
  }
  return reason
}
