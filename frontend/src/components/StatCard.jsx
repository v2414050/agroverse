import Icon from './Icon.jsx'
import './components.css'

/**
 * Reusable dashboard metric card.
 * Always prints a "demonstration data" footnote so demo values are never
 * mistaken for live sensor readings.
 */
export default function StatCard({
  icon,
  label,
  value,
  unit,
  sub,
  tone = 'ok',
  bar,
  footer = 'Demonstration data',
}) {
  const toneClass = tone === 'warn' ? ' is-warn' : tone === 'alert' ? ' is-alert' : ''
  const barPct = typeof bar === 'number' ? Math.max(0, Math.min(100, bar)) : null

  return (
    <article className="stat-card">
      <div className="stat-card__head">
        <span className={`stat-card__icon${toneClass}`}>
          <Icon name={icon} size={18} />
        </span>
        <span className="stat-card__label">{label}</span>
      </div>

      <p className={`stat-card__value${toneClass}`}>
        {value}
        {unit && <span className="stat-card__unit">{unit}</span>}
      </p>

      <p className="stat-card__sub">{sub}</p>

      {barPct !== null && (
        <div
          className="meter"
          role="img"
          aria-label={`${Math.round(bar)} percent of reference level`}
        >
          <div className={`meter__fill${toneClass}`} style={{ width: `${barPct}%` }} />
        </div>
      )}

      <p className="stat-card__foot">{footer}</p>
    </article>
  )
}
