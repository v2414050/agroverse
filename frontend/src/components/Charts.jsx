import { useEffect, useRef, useState } from 'react'
import './components.css'

/**
 * Dependency-free SVG charts (no chart library).
 * LineChart covers soil-moisture history; BarChart covers water usage,
 * energy consumption and irrigation history (single or grouped series).
 * Both take already-simulated data — callers label it as such.
 */

/** Track the on-screen width of a container so SVG text never stretches. */
function useWidth(fallback = 560) {
  const ref = useRef(null)
  const [width, setWidth] = useState(fallback)

  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect?.width ?? fallback)
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [fallback])

  return [ref, width]
}

const PAD = { top: 14, right: 14, bottom: 26, left: 44 }

function niceMax(value) {
  if (!Number.isFinite(value) || value <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const scaled = value / magnitude
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10
  return step * magnitude
}

function ChartFrame({ width, height, children, label }) {
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
      className="chart__svg"
    >
      {children}
    </svg>
  )
}

function XLabels({ points, xFor, y, every }) {
  return points.map((point, i) =>
    i % every === 0 || i === points.length - 1 ? (
      <text
        key={point.label + i}
        x={xFor(i)}
        y={y}
        className="chart__tick"
        textAnchor="middle"
      >
        {point.label}
      </text>
    ) : null,
  )
}

/**
 * Multi-line chart.
 * points: [{ label, value }]
 * target: optional reference line value
 */
export function LineChart({
  points = [],
  unit = '%',
  target,
  height = 220,
  label = 'Line chart',
}) {
  const [ref, width] = useWidth()
  const innerW = Math.max(60, width - PAD.left - PAD.right)
  const innerH = height - PAD.top - PAD.bottom

  if (points.length === 0) {
    return (
      <div ref={ref} className="chart chart--empty">
        <p className="empty">{label}: —</p>
      </div>
    )
  }

  const values = points.map((p) => p.value)
  const dataMax = Math.max(...values, target ?? 0)
  const dataMin = Math.min(...values, target ?? Number.POSITIVE_INFINITY)
  const max = niceMax(dataMax * 1.1)
  const min = Math.max(0, Math.floor((dataMin - 5) / 5) * 5)

  const xFor = (i) =>
    PAD.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW)
  const yFor = (v) =>
    PAD.top + innerH - ((v - min) / (max - min || 1)) * innerH

  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xFor(i).toFixed(1)},${yFor(p.value).toFixed(1)}`)
    .join(' ')
  const areaPath = `${linePath} L${xFor(points.length - 1).toFixed(1)},${PAD.top + innerH} L${xFor(0).toFixed(1)},${PAD.top + innerH} Z`

  const every = Math.max(1, Math.ceil(points.length / 6))

  return (
    <div ref={ref} className="chart">
      <ChartFrame width={width} height={height} label={label}>
        {[0, 0.5, 1].map((frac) => {
          const y = PAD.top + (1 - frac) * (height - PAD.top - PAD.bottom)
          return (
            <g key={frac}>
              <line
                x1={PAD.left}
                x2={PAD.left + innerW}
                y1={y}
                y2={y}
                className="chart__grid"
              />
              <text x={PAD.left - 8} y={y + 4} className="chart__tick" textAnchor="end">
                {Math.round(min + (max - min) * frac)}
                {unit === '%' ? '%' : ''}
              </text>
            </g>
          )
        })}

        {target !== undefined && target !== null && (
          <g>
            <line
              x1={PAD.left}
              x2={PAD.left + innerW}
              y1={yFor(target)}
              y2={yFor(target)}
              className="chart__target"
            />
            <text
              x={PAD.left + innerW}
              y={yFor(target) - 5}
              className="chart__target-label"
              textAnchor="end"
            >
              {target}
              {unit === '%' ? '%' : ''}
            </text>
          </g>
        )}

        <path d={areaPath} className="chart__area" />
        <path d={linePath} className="chart__line" />

        <XLabels points={points} xFor={xFor} y={height - 8} every={every} />
      </ChartFrame>
    </div>
  )
}

/**
 * Bar chart with one or more grouped series.
 * rows: [{ label, [key]: value }]
 * series: [{ key, label, color }]
 * target: optional reference line value
 */
export function BarChart({
  rows = [],
  series = [],
  height = 220,
  unit = '',
  target,
  label = 'Bar chart',
  formatValue,
}) {
  const [ref, width] = useWidth()
  const innerW = Math.max(60, width - PAD.left - PAD.right)
  const innerH = height - PAD.top - PAD.bottom

  if (rows.length === 0 || series.length === 0) {
    return (
      <div ref={ref} className="chart chart--empty">
        <p className="empty">{label}: —</p>
      </div>
    )
  }

  const maxValue = Math.max(
    target ?? 0,
    ...rows.flatMap((row) => series.map((s) => row[s.key] ?? 0)),
  )
  const max = niceMax(maxValue * 1.1)

  const band = innerW / rows.length
  const groupW = Math.max(6, band * 0.68)
  const barW = Math.max(2, (groupW - (series.length - 1) * 2) / series.length)
  const yFor = (v) => PAD.top + innerH - (v / (max || 1)) * innerH

  const every = Math.max(1, Math.ceil(rows.length / 7))
  const xLabelFor = (i) => PAD.left + band * i + band / 2

  return (
    <div ref={ref} className="chart">
      <ChartFrame width={width} height={height} label={label}>
        {[0, 0.5, 1].map((frac) => {
          const y = PAD.top + (1 - frac) * (height - PAD.top - PAD.bottom)
          return (
            <g key={frac}>
              <line
                x1={PAD.left}
                x2={PAD.left + innerW}
                y1={y}
                y2={y}
                className="chart__grid"
              />
              <text x={PAD.left - 8} y={y + 4} className="chart__tick" textAnchor="end">
                {Math.round(max * frac)}
                {unit === '%' ? '%' : ''}
              </text>
            </g>
          )
        })}

        {target !== undefined && target !== null && (
          <line
            x1={PAD.left}
            x2={PAD.left + innerW}
            y1={yFor(target)}
            y2={yFor(target)}
            className="chart__target"
          />
        )}

        {rows.map((row, i) => {
          const groupLeft = PAD.left + band * i + (band - groupW) / 2
          return (
            <g key={row.label + i}>
              {series.map((s, si) => {
                const value = row[s.key] ?? 0
                const barH = Math.max(1, (value / (max || 1)) * innerH)
                const x = groupLeft + si * (barW + 2)
                const y = PAD.top + innerH - barH
                return (
                  <rect
                    key={s.key}
                    x={x.toFixed(1)}
                    y={y.toFixed(1)}
                    width={barW.toFixed(1)}
                    height={barH.toFixed(1)}
                    rx={2}
                    className={`chart__bar chart__bar--${s.color}`}
                  >
                    <title>
                      {row.label} · {s.label}:{' '}
                      {formatValue ? formatValue(value) : value}
                      {unit}
                    </title>
                  </rect>
                )
              })}
            </g>
          )
        })}

        <XLabels
          points={rows.map((r) => ({ label: r.label }))}
          xFor={xLabelFor}
          y={height - 8}
          every={every}
        />
      </ChartFrame>

      <ul className="chart__legend">
        {series.map((s) => (
          <li key={s.key} className="chart__legend-item">
            <span className={`chart__swatch chart__swatch--${s.color}`} />
            {s.label}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default LineChart
