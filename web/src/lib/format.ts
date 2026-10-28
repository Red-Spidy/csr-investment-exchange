const IN = 'en-IN'

/** ₹24,00,000 (Indian digit grouping). */
export function inr(n: number, dp = 0): string {
  const sign = n < 0 ? '-' : ''
  return `${sign}₹${Math.abs(n).toLocaleString(IN, { minimumFractionDigits: dp, maximumFractionDigits: dp })}`
}

/** ₹24 lakh, ₹1.64 crore. Falls back to grouped rupees below a lakh. */
export function inrCompact(n: number): string {
  const abs = Math.abs(n)
  const trim = (x: number) => String(Math.round(x * 100) / 100)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e7) return `${sign}₹${trim(abs / 1e7)} crore`
  if (abs >= 1e5) return `${sign}₹${trim(abs / 1e5)} lakh`
  return inr(n)
}

export function num(n: number, dp = 2): string {
  return n.toLocaleString(IN, { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

export function pct(fraction: number, dp = 0): string {
  return `${(fraction * 100).toFixed(dp)}%`
}

/** Date-only strings (YYYY-MM-DD) are shown as written, never shifted by timezone. */
export function dateShort(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
    timeZone: iso.length === 10 ? 'UTC' : undefined,
  })
}

export function monthLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export function timeShort(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

export function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export function addDays(d: Date, days: number): Date {
  return new Date(d.getTime() + days * 86_400_000)
}

/** 6.9, 8, 1.25: at most two decimals, without trailing zeros. */
export function shortNum(n: number): string {
  return String(Math.round(n * 100) / 100)
}

/** toFixed that never prints "-0.00" for a value that rounds to zero. */
export function fixed(n: number, dp: number): string {
  const out = n.toFixed(dp)
  return Number(out) === 0 ? (0).toFixed(dp) : out
}
