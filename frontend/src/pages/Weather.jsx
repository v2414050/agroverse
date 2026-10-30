import { useCallback, useEffect, useState } from 'react'
import Panel from '../components/Panel.jsx'
import StatCard from '../components/StatCard.jsx'
import PageHeader, { ScopeNote } from './PageHeader.jsx'
import { useLang } from '../i18n.jsx'
import { formatDateTime, formatDay } from '../lib/format.js'

/**
 * Weather & rainfall page — live environmental data from the backend's
 * /api/weather endpoints (Open-Meteo models).
 *
 * Honesty rules mirrored from the backend schema:
 *   current.kind  = "model_based_current"      (not a field sensor)
 *   rainfall.rolling_24h_kind / daily_history_kind / forecast.kind are
 *   shown as distinct labelled blocks, and any null value renders as
 *   "unavailable" (—), never as 0.
 *
 * Everything on this page is EXTERNAL data — it is deliberately separate
 * from the simulated sensor readings used by the irrigation engine.
 */

const STORAGE_KEY = 'ks.weather.place'

async function getJson(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
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

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const mm = (v) => (isNum(v) ? `${v} mm` : null)
const pct = (v) => (isNum(v) ? `${Math.round(v)} %` : null)
const dash = (v) => v ?? '—'

/** Last selected location, restored synchronously from localStorage. */
function readSavedPlace() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (saved && isNum(saved.latitude) && isNum(saved.longitude)) return saved
  } catch {
    /* storage unavailable — start without a selection */
  }
  return null
}

function Unavailable({ label }) {
  const { t } = useLang()
  return (
    <span className="badge badge--neutral" title={label}>
      {t('wthr.unavailable')}
    </span>
  )
}

export default function Weather() {
  const { t } = useLang()

  const [query, setQuery] = useState('')
  const [candidates, setCandidates] = useState(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(null)

  const [place, setPlace] = useState(readSavedPlace)
  const [summary, setSummary] = useState(null)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [summaryError, setSummaryError] = useState(null)

  // Soil is fetched independently of the weather summary: if the soil
  // provider fails (it is currently in a degraded state), weather must
  // keep working and vice versa.
  const [soil, setSoil] = useState(null)
  const [loadingSoil, setLoadingSoil] = useState(false)
  const [soilError, setSoilError] = useState(null)

  const loadSummary = useCallback(async (selected) => {
    setLoadingSummary(true)
    setSummaryError(null)
    setSummary(null)
    try {
      const params = new URLSearchParams({
        latitude: String(selected.latitude),
        longitude: String(selected.longitude),
      })
      setSummary(await getJson(`/api/weather/summary?${params}`))
    } catch (err) {
      setSummaryError(err.message)
    } finally {
      setLoadingSummary(false)
    }
  }, [])

  const loadSoil = useCallback(async (selected) => {
    setLoadingSoil(true)
    setSoilError(null)
    setSoil(null)
    try {
      const params = new URLSearchParams({
        latitude: String(selected.latitude),
        longitude: String(selected.longitude),
      })
      setSoil(await getJson(`/api/weather/soil?${params}`))
    } catch (err) {
      setSoilError(err.message)
    } finally {
      setLoadingSoil(false)
    }
  }, [])

  const select = useCallback(
    (chosen) => {
      setPlace(chosen)
      setCandidates(null)
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(chosen))
      } catch {
        /* storage unavailable — selection still works for this session */
      }
      loadSummary(chosen)
      loadSoil(chosen)
    },
    [loadSummary, loadSoil],
  )

  // Fetch weather + soil once for the restored location, if there is one.
  useEffect(() => {
    const saved = readSavedPlace()
    if (saved) {
      loadSummary(saved)
      loadSoil(saved)
    }
    // mount-only: initial fetch for the persisted location
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const search = useCallback(
    async (event) => {
      event?.preventDefault()
      const q = query.trim()
      setCandidates(null)
      setSearchError(null)
      if (q.length < 2) {
        setSearchError(t('wthr.shortQuery'))
        return
      }
      setSearching(true)
      try {
        const json = await getJson(
          `/api/weather/locations?${new URLSearchParams({ query: q, count: 6 })}`,
        )
        const results = json.results ?? []
        if (results.length === 1) {
          // A single unambiguous match can be used directly; anything
          // else waits for the user's explicit choice.
          select(results[0])
        } else {
          setCandidates(results)
        }
      } catch (err) {
        setSearchError(err.message)
      } finally {
        setSearching(false)
      }
    },
    [query, select, t],
  )

  const freshness = (meta) => {
    if (!meta) return null
    const when = meta.fetched_at
      ? formatDateTime(String(meta.fetched_at).slice(0, 16))
      : '—'
    const state = meta.from_cache
      ? t('wthr.meta.cached', { age: dash(meta.age_seconds) })
      : t('wthr.meta.live')
    return `${t('wthr.meta.retrieved')} ${when} · ${state} · ${
      meta.attribution ?? meta.provider ?? ''
    }`
  }

  const current = summary?.current
  const rainfall = summary?.rainfall
  const forecastDays = summary?.forecast?.days ?? []
  const history = rainfall?.daily_history ?? []

  return (
    <div className="page">
      <PageHeader
        eyebrow={t('wthr.eyebrow')}
        title={t('wthr.title')}
        description={t('wthr.desc')}
      />

      {/* ---- location search ---- */}
      <Panel title={t('wthr.search.label')}>
        <form onSubmit={search} className="form-grid">
          <label className="form-field" htmlFor="weather-query">
            <span className="form-field__label">{t('wthr.search.label')}</span>
            <input
              id="weather-query"
              className="input"
              type="search"
              value={query}
              placeholder={t('wthr.search.placeholder')}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn--primary" disabled={searching}>
            {searching ? t('wthr.searching') : t('wthr.search.action')}
          </button>
        </form>

        {searchError && (
          <p className="form-error" role="alert">
            {t('wthr.searchError')} {searchError}
          </p>
        )}

        {candidates !== null && candidates.length === 0 && (
          <p className="note">{t('wthr.noMatch')}</p>
        )}

        {candidates !== null && candidates.length > 0 && (
          <>
            <h3 className="panel__title">{t('wthr.candidates.title')}</h3>
            <p className="panel__sub">{t('wthr.candidates.sub')}</p>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('wthr.candidates.place')}</th>
                    <th>{t('wthr.candidates.region')}</th>
                    <th>{t('wthr.candidates.country')}</th>
                    <th>{t('wthr.candidates.coords')}</th>
                    <th aria-label={t('wthr.candidates.use')} />
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((item) => (
                    <tr key={`${item.name}-${item.latitude}-${item.longitude}`}>
                      <td>{item.name}</td>
                      <td>{dash([item.admin2, item.admin1].filter(Boolean).join(', ') || null)}</td>
                      <td>{dash(item.country)}</td>
                      <td className="tnum">
                        {item.latitude.toFixed(3)}, {item.longitude.toFixed(3)}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost"
                          onClick={() => select(item)}
                        >
                          {t('wthr.candidates.use')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {place && (
          <p className="note">
            <strong>{t('wthr.meta.location')}:</strong> {place.label ?? place.name}
          </p>
        )}
      </Panel>

      {!place && <ScopeNote>{t('wthr.scopeNote')}</ScopeNote>}

      {loadingSummary && <p className="note">{t('wthr.loading')}</p>}

      {summaryError && (
        <Panel title={t('wthr.summaryError')}>
          <p className="form-error" role="alert">
            {summaryError}
          </p>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => place && loadSummary(place)}
          >
            {t('wthr.retry')}
          </button>
        </Panel>
      )}

      {/* ---- live data sections ---- */}
      {summary && current && (
        <>
          <Panel
            title={t('wthr.current.title')}
            subtitle={`${dash(current.condition)} · ${dash(
              current.observed_local,
            )} — ${freshness(summary.meta)}`}
          >
            <p className="badge badge--info">{t('wthr.kind.current')}</p>
            <div className="cards">
              <StatCard
                icon="gauge"
                label={t('wthr.card.temp')}
                value={isNum(current.temperature_c) ? current.temperature_c : '—'}
                unit={isNum(current.temperature_c) ? '°C' : undefined}
                sub={dash(current.condition)}
                footer={t('wthr.kind.current')}
              />
              <StatCard
                icon="dropcount"
                label={t('wthr.card.humidity')}
                value={pct(current.humidity_pct) ?? t('wthr.unavailable')}
                sub={t('wthr.meta.units')}
                footer={t('wthr.kind.current')}
              />
              <StatCard
                icon="cloud"
                label={t('wthr.card.precip')}
                value={mm(current.precipitation_mm) ?? t('wthr.unavailable')}
                sub={t('wthr.rain.rolling')}
                footer={t('wthr.kind.current')}
              />
              <StatCard
                icon="bolt"
                label={t('wthr.card.wind')}
                value={
                  isNum(current.wind_speed_kmh)
                    ? current.wind_speed_kmh
                    : t('wthr.unavailable')
                }
                unit={isNum(current.wind_speed_kmh) ? 'km/h' : undefined}
                sub={`${t('wthr.card.cloud')}: ${
                  pct(current.cloud_cover_pct) ?? t('wthr.unavailable')
                }`}
                footer={t('wthr.kind.current')}
              />
            </div>
            <p className="panel__sub">{current.note}</p>
          </Panel>

          {rainfall && (
            <Panel title={t('wthr.rain.title')} subtitle={freshness(summary.meta)}>
              <p className="badge badge--info">{t('wthr.kind.rolling')}</p>
              <dl className="def-list">
                <dt>{t('wthr.rain.rolling')}</dt>
                <dd>
                  {mm(rainfall.rolling_24h_mm) ?? <Unavailable />}
                  {isNum(rainfall.rolling_24h_hours_covered) &&
                    rainfall.rolling_24h_hours_covered < 24 &&
                    ` (${rainfall.rolling_24h_hours_covered} h)`}
                </dd>
                <dt>{t('wthr.rain.period')}</dt>
                <dd>{dash(rainfall.rolling_24h_period)}</dd>
              </dl>
              <p className="panel__sub">{rainfall.rolling_24h_note}</p>

              <p className="badge badge--info">{t('wthr.kind.history')}</p>
              {history.length === 0 ? (
                <p className="note">{t('wthr.rain.noHistory')}</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t('wthr.rain.date')}</th>
                        <th>{t('wthr.rain.mm')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((day) => (
                        <tr key={day.date}>
                          <td>{formatDay(day.date)}</td>
                          <td className="tnum">
                            {mm(day.precipitation_mm) ?? <Unavailable />}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="panel__sub">{rainfall.daily_history_note}</p>
            </Panel>
          )}

          {summary.forecast && (
            <Panel
              title={t('wthr.fc.title')}
              subtitle={`${t('wthr.meta.units')} ${freshness(summary.meta)}`}
            >
              <p className="badge badge--info">{t('wthr.kind.forecast')}</p>
              {forecastDays.length === 0 ? (
                <p className="note">{t('wthr.fc.empty')}</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t('wthr.fc.day')}</th>
                        <th>{t('wthr.fc.min')}</th>
                        <th>{t('wthr.fc.max')}</th>
                        <th>{t('wthr.fc.rain')}</th>
                        <th>{t('wthr.fc.prob')}</th>
                        <th>{t('wthr.fc.condition')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {forecastDays.map((day) => (
                        <tr key={day.date}>
                          <td>
                            {dash(day.weekday)} · {formatDay(day.date)}
                          </td>
                          <td className="tnum">{isNum(day.temp_min_c) ? `${day.temp_min_c} °C` : '—'}</td>
                          <td className="tnum">{isNum(day.temp_max_c) ? `${day.temp_max_c} °C` : '—'}</td>
                          <td className="tnum">{mm(day.precipitation_mm) ?? <Unavailable />}</td>
                          <td className="tnum">
                            {pct(day.precipitation_probability_max_pct) ?? <Unavailable />}
                          </td>
                          <td>{dash(day.condition)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="panel__sub">{summary.forecast.note}</p>
            </Panel>
          )}

          <ScopeNote>{t('wthr.scopeNote')}</ScopeNote>
        </>
      )}

      {/* ---- soil (independent provider — must never break weather) ---- */}
      {loadingSoil && <p className="note">{t('wthr.soil.loading')}</p>}

      {soilError && (
        <Panel title={t('wthr.soil.error')}>
          <p className="form-error" role="alert">
            {soilError}
          </p>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => place && loadSoil(place)}
          >
            {t('wthr.retry')}
          </button>
        </Panel>
      )}

      {soil && (
        <Panel
          title={t('wthr.soil.title')}
          subtitle={`${soil.meta?.resolution ?? ''} · ${freshness(soil.meta)}`}
        >
          {soil.available ? (
            <>
              <p className="badge badge--info">{t('wthr.soil.kind')}</p>
              <p>
                <strong>{t('wthr.soil.texture')}:</strong>{' '}
                {soil.texture_class ?? t('wthr.unavailable')}
                {soil.texture_class_depth ? ` (${soil.texture_class_depth})` : ''}
              </p>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t('wthr.soil.depth')}</th>
                      <th>{t('wthr.soil.sand')}</th>
                      <th>{t('wthr.soil.silt')}</th>
                      <th>{t('wthr.soil.clay')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(soil.layers ?? []).map((layer) => (
                      <tr key={layer.depth}>
                        <td>{layer.depth}</td>
                        <td className="tnum">{pct(layer.sand_pct) ?? '—'}</td>
                        <td className="tnum">{pct(layer.silt_pct) ?? '—'}</td>
                        <td className="tnum">{pct(layer.clay_pct) ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="note">{soil.meta?.disclaimer}</p>
            </>
          ) : (
            <>
              <p className="badge badge--warning">{t('wthr.soil.unavailableTitle')}</p>
              <p className="note">{soil.message ?? t('wthr.unavailable')}</p>
              <p className="panel__sub">{t('wthr.soil.disclaimer')}</p>
            </>
          )}
        </Panel>
      )}
    </div>
  )
}
