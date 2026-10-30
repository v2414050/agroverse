import { useCallback, useEffect, useState } from 'react'
import Panel from '../components/Panel.jsx'
import PageHeader, { ScopeNote } from './PageHeader.jsx'
import { useLang } from '../i18n.jsx'
import { formatDateTime, formatLitres, percent } from '../lib/format.js'

const THRESHOLD = 35

const STATUS_TONE = {
  DRY: 'critical',
  OPTIMAL: 'ok',
  HIGH: 'warning',
  SATURATED: 'info',
  UNKNOWN: 'neutral',
}

function moistureTone(value) {
  if (value < THRESHOLD) return 'critical'
  if (value < 40) return 'warning'
  return 'ok'
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  })
  const json = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = json?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).join('; ')
          : `Request failed (HTTP ${response.status}).`
    throw new Error(message)
  }
  return json
}

function ConfidenceBadge({ confidence }) {
  const { t } = useLang()
  const tone = confidence === 'high' ? 'ok' : confidence === 'medium' ? 'warning' : 'critical'
  const key = `conf.${confidence}`
  const label = t(key)
  return (
    <span className={`badge badge--${tone}`}>
      {label === key ? `${confidence} confidence` : label}
    </span>
  )
}

export default function Irrigation({ data }) {
  const { t } = useLang()
  const zones = data.dashboard.irrigation.zones
  const history = data.dashboard.irrigation.history ?? []
  const dry = zones.filter((z) => z.status === 'needs_water')

  // Translate the engine's action code; fall back to its English label.
  const actionLabel = (code, fallback) => {
    if (!code) return fallback
    const key = `irrig.action.${code}`
    const label = t(key)
    return label === key ? fallback : label
  }

  const zoneNames = [...new Set(zones.map((z) => z.zone))].sort()
  const [zone, setZone] = useState(zoneNames[0] ?? 'Zone A')
  const [scenarios, setScenarios] = useState([])
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [activeScenario, setActiveScenario] = useState(null)

  useEffect(() => {
    let stale = false
    fetch('/api/irrigation/scenarios', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        if (!stale) setScenarios(d.scenarios ?? [])
      })
      .catch(() => {
        if (!stale) setScenarios([])
      })
    return () => {
      stale = true
    }
  }, [])

  const analyze = useCallback(async (body, scenarioId = null) => {
    setBusy(true)
    setError(null)
    setActiveScenario(scenarioId)
    try {
      setResult(await postJson('/api/irrigation/analyze', body))
    } catch (err) {
      setResult(null)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [])

  const target = result?.target
  const confidenceReasons = result?.confidence?.reasons ?? []

  return (
    <div className="page">
      <PageHeader
        eyebrow={t('irr.eyebrow')}
        title={t('irr.title')}
        description={t('irr.desc')}
      />

      <div className="tile-grid section-gap">
        <div className="tile">
          <p className="tile__label">{t('irr.tile.zones')}</p>
          <p className="tile__value">{zones.length}</p>
          <p className="tile__meta">{t('irr.tile.zonesMeta')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('irr.tile.dry')}</p>
          <p className="tile__value">{dry.length}</p>
          <p className="tile__meta">{t('irr.tile.dryMeta', { threshold: THRESHOLD })}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('irr.tile.ok')}</p>
          <p className="tile__value">{zones.length - dry.length}</p>
          <p className="tile__meta">{t('irr.tile.okMeta')}</p>
        </div>
      </div>

      <div className="section-gap">
        <Panel
          title={t('irr.analysisPanel')}
          subtitle={t('irr.analysisPanel.sub')}
          action={<span className="badge badge--neutral">{t('common.simulated')}</span>}
        >
          <div className="analyze-bar">
            <label className="analyze-bar__label" htmlFor="zone-select">
              {t('table.zone')}
            </label>
            <select
              id="zone-select"
              className="select"
              value={zone}
              onChange={(e) => setZone(e.target.value)}
            >
              {zoneNames.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => analyze({ zone })}
              disabled={busy}
            >
              {busy && !activeScenario ? t('irr.analyzing') : t('irr.analyze')}
            </button>
          </div>

          {scenarios.length > 0 && (
            <div className="scenario-row">
              <span className="scenario-row__label">{t('irr.scenarios')}</span>
              {scenarios.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`btn btn--ghost${activeScenario === s.id ? ' is-active' : ''}`}
                  title={s.description}
                  disabled={busy}
                  onClick={() => analyze(s.overrides, s.id)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}

          {error && (
            <p className="form-error">{t('irr.analysisFailed', { msg: error })}</p>
          )}

          {result && (
            <div className="analysis">
              <div className="analysis__head">
                <span className={`badge badge--${STATUS_TONE[result.status] ?? 'neutral'}`}>
                  {t(`engine.status.${result.status}`)}
                </span>
                <strong className="analysis__action">
                  {actionLabel(result.action, result.action_label)}
                </strong>
                <ConfidenceBadge confidence={result.confidence.level} />
                <span className="tag">{result.source}</span>
              </div>

              <p className="analysis__why">{result.explanation}</p>

              <dl className="def-list analysis__facts">
                <div>
                  <dt>{t('irr.fact.moisture')}</dt>
                  <dd>{percent(result.current_moisture_pct)}</dd>
                </div>
                <div>
                  <dt>{t('irr.fact.target')}</dt>
                  <dd>
                    {target
                      ? `${target.lower_pct}% – ${target.upper_pct}%`
                      : '—'}
                  </dd>
                </div>
                <div>
                  <dt>{t('irr.fact.saturation')}</dt>
                  <dd>{target ? percent(target.saturation_pct) : '—'}</dd>
                </div>
                <div>
                  <dt>{t('irr.fact.cropStage')}</dt>
                  <dd>
                    {result.plot.crop || '—'}
                    {result.plot.growth_stage ? ` · ${result.plot.growth_stage}` : ''}
                  </dd>
                </div>
                <div>
                  <dt>{t('irr.fact.rain')}</dt>
                  <dd>
                    {typeof result.rainfall_mm_24h === 'number'
                      ? `${result.rainfall_mm_24h} mm`
                      : t('irr.notAvailable')}{' '}
                    {result.rain_advises_pause && (
                      <span className="badge badge--warning">{t('irr.pauseAdvised')}</span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{t('irr.fact.refill')}</dt>
                  <dd>
                    {result.suggested_volume_l
                      ? `${formatLitres(result.suggested_volume_l)} · ~${result.suggested_duration_min} min pump`
                      : t('irr.notNeeded')}
                  </dd>
                </div>
              </dl>

              {confidenceReasons.length > 0 && (
                <p className="analysis__caveat">
                  <strong>{t('irr.dataQuality')}</strong> {confidenceReasons.join(' ')}
                </p>
              )}

              <p className="analysis__disclaimer">{t('irr.disclaimer')}</p>
            </div>
          )}

          {!result && !error && (
            <p className="empty">{t('irr.emptyHint')}</p>
          )}
        </Panel>
      </div>

      <div className="section-gap">
        <Panel
          title={t('panel.zones')}
          subtitle={t('panel.zones.sub', { threshold: THRESHOLD })}
          flush
        >
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('table.zone')}</th>
                  <th>{t('table.plot')}</th>
                  <th>{t('table.soilMoisture')}</th>
                  <th>{t('irr.threshold')}</th>
                  <th>{t('table.status')}</th>
                  <th>{t('irr.engineAdvice')}</th>
                </tr>
              </thead>
              <tbody>
                {zones.map((zoneRow) => {
                  const tone = moistureTone(zoneRow.soil_moisture_pct)
                  const advice = zoneRow.advice
                  return (
                    <tr key={`${zoneRow.zone}-${zoneRow.plot}`}>
                      <td>{zoneRow.zone}</td>
                      <td>{zoneRow.plot}</td>
                      <td className="tnum">{percent(zoneRow.soil_moisture_pct)}</td>
                      <td className="tnum">{THRESHOLD}%</td>
                      <td>
                        <span className={`badge badge--${tone}`}>
                          {zoneRow.status === 'needs_water'
                            ? t('irr.needsWater')
                            : t('irr.ok')}
                        </span>
                      </td>
                      <td>
                        {advice ? (
                          <span className={`badge badge--${STATUS_TONE[advice.status] ?? 'neutral'}`}>
                            {t(`engine.status.${advice.status}`)}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <div className="section-gap">
        <Panel title={t('irr.historyTable')} subtitle={t('irr.historySub')} flush>
          {history.length === 0 ? (
            <p className="empty">{t('empty.irrigation')}</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('table.started')}</th>
                    <th>{t('table.zone')}</th>
                    <th>{t('table.plot')}</th>
                    <th>{t('table.duration')}</th>
                    <th>{t('table.water')}</th>
                    <th>{t('table.method')}</th>
                    <th>{t('table.status')}</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id}>
                      <td>{formatDateTime(h.started_at)}</td>
                      <td>{h.zone}</td>
                      <td>{h.plot ?? '—'}</td>
                      <td className="tnum">{h.duration_min} min</td>
                      <td className="tnum">{formatLitres(h.litres)}</td>
                      <td>{h.method}</td>
                      <td>
                        <span className="badge badge--ok">
                          {h.status === 'completed' ? t('irr.completed') : h.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <ScopeNote>{t('irr.scopeNote')}</ScopeNote>
    </div>
  )
}
