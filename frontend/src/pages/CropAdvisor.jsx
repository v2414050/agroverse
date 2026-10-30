import { useCallback, useEffect, useState } from 'react'
import Panel from '../components/Panel.jsx'
import Icon from '../components/Icon.jsx'
import PageHeader, { ScopeNote } from './PageHeader.jsx'
import { useLang } from '../i18n.jsx'
import { percent } from '../lib/format.js'

/** Display-only suitability flag for the currently planted crops. */
function isSuitable(plot) {
  return plot.health_pct >= 70 && plot.soil_moisture_pct >= 30
}

function SuitabilityBadge({ plot }) {
  const { t } = useLang()
  return isSuitable(plot) ? (
    <span className="badge badge--ok">{t('crops.suitable')}</span>
  ) : (
    <span className="badge badge--warning">{t('crops.attention')}</span>
  )
}

const VERDICT_TONE = {
  recommended: 'ok',
  suitable_with_caution: 'warning',
  marginal: 'warning',
  not_recommended: 'critical',
}

/* Form state: every value is a string; '' means "not provided" and is
 * simply omitted from the request — the engine reports it as missing. */
const EMPTY_FORM = {
  soil_type: '',
  soil_ph: '',
  nitrogen_kg_ha: '',
  phosphorus_kg_ha: '',
  potassium_kg_ha: '',
  temperature_c: '',
  rainfall_mm: '',
  water_availability: '',
  season: '',
  slope_pct: '',
}

/* Sample scenarios (simulated) that exercise the real engine paths. */
const SCENARIOS = [
  {
    id: 'good',
    label: 'crops.scen.good',
    description: 'crops.scen.goodDesc',
    values: {
      soil_type: 'Loamy', soil_ph: '6.8', nitrogen_kg_ha: '90',
      phosphorus_kg_ha: '45', potassium_kg_ha: '40', temperature_c: '26',
      rainfall_mm: '850', water_availability: 'limited', season: 'kharif',
      slope_pct: '2',
    },
  },
  {
    id: 'poor',
    label: 'crops.scen.poor',
    description: 'crops.scen.poorDesc',
    values: {
      soil_type: 'Sandy', soil_ph: '4.5', nitrogen_kg_ha: '20',
      phosphorus_kg_ha: '10', potassium_kg_ha: '10', temperature_c: '40',
      rainfall_mm: '100', water_availability: 'rainfed', season: 'zaid',
      slope_pct: '20',
    },
  },
  {
    id: 'missing',
    label: 'crops.scen.missing',
    description: 'crops.scen.missingDesc',
    values: {},
  },
]

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

function Reasons({ title, items, tone }) {
  if (!items?.length) return null
  return (
    <>
      <p className="analysis__caveat" style={{ marginTop: 10, marginBottom: 2 }}>
        <strong>{title}</strong>
      </p>
      <ul className="crop-reasons">
        {items.map((text, i) => (
          <li key={i} style={tone ? { color: tone } : undefined}>
            {text}
          </li>
        ))}
      </ul>
    </>
  )
}

function CropCard({ item }) {
  const { t } = useLang()
  const score = item.score ?? 0
  const tone = VERDICT_TONE[item.verdict] ?? 'neutral'
  const verdictKey = `verdict.${item.verdict}`
  const verdictLabel = t(verdictKey)
  const meterClass = tone === 'ok' ? '' : tone === 'critical' ? ' is-alert' : ' is-warn'
  const fert = item.fertilizer

  return (
    <article className="stat-card">
      <div className="stat-card__head">
        <span
          className={`stat-card__icon${tone === 'critical' ? ' is-alert' : tone === 'warning' ? ' is-warn' : ''}`}
        >
          <Icon name="sprout" size={18} />
        </span>
        <span className="stat-card__label">{item.crop}</span>
      </div>

      <p className={`stat-card__value${tone === 'critical' ? ' is-alert' : tone === 'warning' ? ' is-warn' : ''}`}>
        {item.score ?? '—'}
        <span className="stat-card__unit">{t('crops.fit100')}</span>
      </p>
      <div className="meter">
        <div className={`meter__fill${meterClass}`} style={{ width: `${score}%` }} />
      </div>

      <p className="stat-card__sub">
        <span className={`badge badge--${tone}`}>
          {verdictLabel === verdictKey ? item.verdict_label : verdictLabel}
        </span>{' '}
        {item.provisional && (
          <span className="badge badge--neutral">{t('tag.provisionalShort')}</span>
        )}
      </p>

      <p style={{ fontSize: 13, color: 'var(--muted)', margin: 0 }}>{item.explanation}</p>

      <Reasons title={t('crops.reasons.favorable')} items={item.favorable} />
      <Reasons title={t('crops.reasons.limiting')} items={item.limiting} />
      <Reasons title={t('crops.reasons.missing')} items={item.missing} />

      {fert && (
        <>
          <p className="analysis__caveat" style={{ marginTop: 10, marginBottom: 2 }}>
            <strong>{t('crops.fertilizer')}</strong>
          </p>
          <p style={{ fontSize: 12.5, color: 'var(--muted)', margin: 0 }}>{fert.advice}</p>
        </>
      )}

      {item.next_steps?.length > 0 && (
        <>
          <p className="analysis__caveat" style={{ marginTop: 10, marginBottom: 2 }}>
            <strong>{t('crops.nextSteps')}</strong>
          </p>
          <ul className="crop-reasons">
            {item.next_steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ul>
        </>
      )}

      <p className="stat-card__foot">
        {item.requirements?.note || t('crops.demoProfile')}
      </p>
    </article>
  )
}

const NUMBER_FIELDS = [
  ['soil_ph', 'crops.field.ph', 'crops.hint.ph'],
  ['temperature_c', 'crops.field.temp', 'crops.hint.temp'],
  ['rainfall_mm', 'crops.field.rain', 'crops.hint.rain'],
  ['slope_pct', 'crops.field.slope', 'crops.hint.slope'],
  ['nitrogen_kg_ha', 'crops.field.n', 'crops.hint.npk'],
  ['phosphorus_kg_ha', 'crops.field.p', 'crops.hint.npk'],
  ['potassium_kg_ha', 'crops.field.k', 'crops.hint.npk'],
]

export default function CropAdvisor({ data }) {
  const { t } = useLang()
  const crops = data.dashboard.crops
  const farm = data.dashboard.farm
  const suitable = crops.filter(isSuitable)

  const [reference, setReference] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [offline, setOffline] = useState(false)
  const [activeScenario, setActiveScenario] = useState(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let stale = false
    fetch('/api/crops/reference', { headers: { Accept: 'application/json' } })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((ref) => {
        if (stale) return
        setReference(ref)
        setOffline(false)
        // Default the season select to the current calendar season.
        const current = ref.seasons?.find((s) => s.current)
        if (current) setForm((f) => ({ ...f, season: f.season || current.key }))
      })
      .catch(() => {
        if (!stale) setOffline(true)
      })
    return () => {
      stale = true
    }
  }, [])

  const setField = (name, value) => {
    setForm((f) => ({ ...f, [name]: value }))
    setActiveScenario(null)
  }

  const prefillFromFarm = () => {
    if (!farm) return
    setForm((f) => ({
      ...f,
      soil_type: f.soil_type || farm.soil_type || '',
      soil_ph: f.soil_ph || (farm.soil_ph != null ? String(farm.soil_ph) : ''),
    }))
    setActiveScenario(null)
  }

  const analyze = useCallback(async (values) => {
    setBusy(true)
    setError(null)
    try {
      const body = {}
      for (const [key, raw] of Object.entries(values)) {
        if (raw === '' || raw == null) continue // omitted -> reported missing
        body[key] = typeof raw === 'string' && Number.isFinite(Number(raw)) && key !== 'soil_type' && key !== 'season' && key !== 'water_availability'
          ? Number(raw)
          : raw
      }
      const next = await postJson('/api/crops/analyze', body)
      setResult(next)
      setShowAll(false)
    } catch (err) {
      setResult(null)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [])

  const ranked = result?.recommendations ?? []
  const shown = showAll ? ranked : ranked.slice(0, 5)
  const summary = result?.summary

  return (
    <div className="page">
      <PageHeader
        eyebrow={t('crops.eyebrow')}
        title={t('crops.title')}
        description={t('crops.desc')}
      />

      <div className="tile-grid section-gap">
        <div className="tile">
          <p className="tile__label">{t('crops.tile.growing')}</p>
          <p className="tile__value">{crops.length}</p>
          <p className="tile__meta">
            {t('crops.meta.growing', {
              names: [...new Set(crops.map((c) => c.crop))].join(', '),
            })}
          </p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('crops.tile.suitable')}</p>
          <p className="tile__value">
            {suitable.length} / {crops.length}
          </p>
          <p className="tile__meta">{t('crops.meta.suitable')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('crops.tile.dataset')}</p>
          <p className="tile__value">{reference?.crops?.length ?? '—'}</p>
          <p className="tile__meta">{t('crops.meta.dataset')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('crops.tile.season')}</p>
          <p className="tile__value" style={{ fontSize: 17 }}>
            {reference?.seasons?.find((s) => s.current)?.label ?? '—'}
          </p>
          <p className="tile__meta">{t('crops.meta.season')}</p>
        </div>
      </div>

      <div className="section-gap">
        <Panel
          title={t('crops.formPanel')}
          subtitle={t('crops.formPanel.sub')}
          action={<span className="badge badge--neutral">{t('crops.demoDataset')}</span>}
        >
          {offline && (
            <p className="empty">{t('crops.offlineNote')}</p>
          )}

          <div className="form-grid">
            <div className="form-field">
              <label htmlFor="ca-soil">{t('form.soilType')}</label>
              <select
                id="ca-soil"
                className="select"
                value={form.soil_type}
                onChange={(e) => setField('soil_type', e.target.value)}
              >
                <option value="">{t('crops.notProvided')}</option>
                {(reference?.soil_types ?? []).map((s) => (
                  <option key={s.key} value={s.label}>{s.label}</option>
                ))}
              </select>
            </div>

            <div className="form-field">
              <label htmlFor="ca-water">{t('crops.field.water')}</label>
              <select
                id="ca-water"
                className="select"
                value={form.water_availability}
                onChange={(e) => setField('water_availability', e.target.value)}
              >
                <option value="">{t('crops.notProvided')}</option>
                {(reference?.water_availability ?? []).map((w) => (
                  <option key={w.key} value={w.key}>{w.label}</option>
                ))}
              </select>
            </div>

            <div className="form-field">
              <label htmlFor="ca-season">{t('crops.field.season')}</label>
              <select
                id="ca-season"
                className="select"
                value={form.season}
                onChange={(e) => setField('season', e.target.value)}
              >
                <option value="">{t('crops.notProvided')}</option>
                {(reference?.seasons ?? []).map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </div>

            {NUMBER_FIELDS.map(([key, labelKey, hintKey]) => (
              <div className="form-field" key={key}>
                <label htmlFor={`ca-${key}`}>{t(labelKey)}</label>
                <input
                  id={`ca-${key}`}
                  className="input"
                  type="number"
                  inputMode="decimal"
                  step="any"
                  placeholder={t(hintKey)}
                  value={form[key]}
                  onChange={(e) => setField(key, e.target.value)}
                />
              </div>
            ))}
          </div>

          <div className="analyze-bar">
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy}
              onClick={() => analyze(form)}
            >
              {busy && !result ? t('crops.analyzing') : t('crops.analyze')}
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={prefillFromFarm}
              title={t('crops.useFarmHint')}
            >
              {t('crops.useFarm')}
            </button>
          </div>

          <div className="scenario-row">
            <span className="scenario-row__label">{t('irr.scenarios')}</span>
            {SCENARIOS.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`btn btn--ghost${activeScenario === s.id ? ' is-active' : ''}`}                  title={t(s.description)}
                  disabled={busy}
                  onClick={() => {
                    const values = { ...EMPTY_FORM, ...s.values }
                    setForm(values)
                    setActiveScenario(s.id)
                    analyze(values)
                  }}
                >
                  {t(s.label)}
                </button>
            ))}
          </div>

          {error && (
            <p className="form-error">{t('crops.analysisFailed', { msg: error })}</p>
          )}

          {!result && !error && !offline && (
            <p className="empty">
              {t('crops.emptyHint', {
                count: reference?.crops?.length ?? t('crops.demoWord'),
              })}
            </p>
          )}

          {result?.insufficient_data && (
            <p className="empty">
              <strong>{t('crops.insufficientTitle')}</strong>
              <br />
              {result.summary?.note}
              <br />
              {t('crops.insufficientHint')}
            </p>
          )}

          {ranked.length > 0 && (
            <div className="analysis">
              <div className="analysis__head">
                <strong className="analysis__action">
                  {t('crops.recommendedOf', {
                    recommended: summary.recommended_count,
                    count: summary.count,
                  })}
                </strong>
                {summary.provisional ? (
                  <span className="badge badge--warning">
                    {t('crops.provisionalBadge')}
                  </span>
                ) : (
                  <span className="badge badge--ok">{t('badge.complete')}</span>
                )}
                <span className="tag">
                  {t('crops.topTag', {
                    crop: summary.top_crop,
                    score: summary.top_score ?? '—',
                  })}
                </span>
              </div>
              <p className="analysis__why">
                <strong>{summary.top_crop}</strong> {t('crops.ranksFirstSuffix')}{' '}
                {ranked[0].explanation}
              </p>
              {result.missing?.length > 0 && (
                <p className="analysis__caveat">
                  <strong>{t('crops.missingInfo')}</strong> {result.missing.join(' ')}
                </p>
              )}
              <p className="analysis__caveat">{summary.note}</p>
            </div>
          )}
        </Panel>
      </div>

      {ranked.length > 0 && (
        <div className="section-gap">
          <div className="cards">
            {shown.map((item) => (
              <CropCard key={item.crop} item={item} />
            ))}
          </div>
          {ranked.length > shown.length && (
            <button
              type="button"
              className="btn"
              onClick={() => setShowAll(true)}
            >
              {t('crops.showAll', { n: ranked.length })}
            </button>
          )}
        </div>
      )}

      <div className="section-gap">
        <Panel title={t('panel.current')} subtitle={t('panel.current.sub')} flush>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('table.plot')}</th>
                  <th>{t('table.crop')}</th>
                  <th>{t('table.stage')}</th>
                  <th>{t('table.health')}</th>
                  <th>{t('table.soilMoisture')}</th>
                  <th>{t('crops.suitability')}</th>
                </tr>
              </thead>
              <tbody>
                {crops.map((plot) => (
                  <tr key={plot.id}>
                    <td>{plot.name}</td>
                    <td>{plot.crop}</td>
                    <td>{plot.growth_stage}</td>
                    <td className="tnum">{plot.health_pct}%</td>
                    <td className="tnum">{percent(plot.soil_moisture_pct)}</td>
                    <td>
                      <SuitabilityBadge plot={plot} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <ScopeNote>{t('crops.scopeNote')}</ScopeNote>
    </div>
  )
}
