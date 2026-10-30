/** Small formatting helpers shared by the pages (no date library needed). */

export const formatNumber = (n) =>
  typeof n === 'number' ? n.toLocaleString('en-US') : '—'

/** Compact litres: 241350 -> "241.4 kL" */
export function formatLitres(litres) {
  if (typeof litres !== 'number') return '—'
  if (litres >= 1_000_000) return `${(litres / 1_000_000).toFixed(2)} M L`
  if (litres >= 1_000) return `${(litres / 1_000).toFixed(1)} kL`
  return `${litres} L`
}

/** 'YYYY-MM-DD' -> '15 Oct' (parsed as a local date, not UTC). */
export function formatDay(isoDate) {
  if (!isoDate) return '—'
  const [y, m, d] = isoDate.slice(0, 10).split('-').map(Number)
  if (!y || !m || !d) return isoDate
  return new Date(y, m - 1, d).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
  })
}

/** 'YYYY-MM-DDTHH:MM' -> '15 Oct, 09:04' */
export function formatDateTime(iso) {
  if (!iso) return '—'
  const [datePart, timePart] = iso.split('T')
  return `${formatDay(datePart)}${timePart ? `, ${timePart}` : ''}`
}

export const percent = (value) =>
  typeof value === 'number' ? `${Math.round(value)}%` : '—'
