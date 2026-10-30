import { useCallback, useEffect, useState } from 'react'
import Panel from '../components/Panel.jsx'
import Icon from '../components/Icon.jsx'
import { BarChart } from '../components/Charts.jsx'
import PageHeader, { ScopeNote } from './PageHeader.jsx'
import { useLang } from '../i18n.jsx'
import { formatDay, formatNumber } from '../lib/format.js'

const SEVERITY_TONE = {
  critical: 'critical',
  warning: 'warning',
  info: 'info',
  ok: 'ok',
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const json = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = json?.detail
    throw new Error(
      typeof detail === 'string' ? detail : `Request failed (HTTP ${response.status}).`,
    )
  }
  return json
}

const RANK = { ok: 0, info: 1, warning: 2, critical: 3 }

function EquipmentCard({ item, busy, onToggle }) {
  const { t } = useLang()
  const issues = item.findings.filter((f) => f.issue !== 'normal')
  const tone = issues.reduce(
    (acc, f) => (RANK[f.severity] > RANK[acc] ? f.severity : acc),
    'ok',
  )

  return (
    <article className="stat-card">
      <div className="stat-card__head">
        <span className={`stat-card__icon${tone === 'ok' ? '' : tone === 'critical' ? ' is-alert' : ' is-warn'}`}>
          <Icon name="bolt" size={18} />
        </span>
        <span className="stat-card__label">{item.equipment}</span>
      </div>

      <p className={`stat-card__value${tone === 'critical' ? ' is-alert' : tone === 'warning' ? ' is-warn' : ''}`}>
        {item.energy.kwh_today ?? '—'}
        <span className="stat-card__unit">{t('energy.kwhToday')}</span>
      </p>

      <p className="stat-card__sub">
        <span className={`badge badge--${item.is_on ? 'ok' : 'neutral'}`}>{item.status_label}</span>{' '}
        <span className="tag">
          {item.energy.basis === 'measured'
            ? t('energy.basis.measured')
            : item.energy.basis === 'estimated'
              ? t('energy.basis.estimated')
              : t('energy.basis.noRating')}
        </span>
        {item.power_kw != null && (
          <span className="tag">{t('energy.rated', { kw: item.power_kw })}</span>
        )}
      </p>

      <div className="analysis__head" style={{ marginTop: 2 }}>
        {item.findings.map((f) => (
          <span key={f.issue} className={`badge badge--${SEVERITY_TONE[f.severity] ?? 'neutral'}`}>
            {t(`engine.issue.${f.issue}`)}
          </span>
        ))}
      </div>

      <p className="stat-card__foot">
        {issues.length
          ? t('energy.savingFoot', { kwh: item.total_savings_kwh_estimate })
          : t('energy.footOk')}
      </p>

      {item.is_on && issues.length > 0 && (
        <button
          type="button"
          className="btn btn--ghost"
          disabled={busy}
          onClick={() => onToggle(item, false)}
        >
          {t('energy.switchOff')}
        </button>
      )}
      {!item.is_on && (
        <button
          type="button"
          className="btn btn--ghost"
          disabled={busy}
          onClick={() => onToggle(item, true)}
        >
          {t('energy.switchOn')}
        </button>
      )}
    </article>
  )
}

export default function Energy({ data }) {
  const { t } = useLang()
  const series = data.dashboard.energy.series

  const total = (key) => series.reduce((sum, d) => sum + (d[key] || 0), 0)
  const solar = total('kwh_solar')
  const grid = total('kwh_grid')
  const pump = total('pump_kwh')

  const [fleet, setFleet] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [offline, setOffline] = useState(false)

  // Pure fetch — state updates happen in callers (effect callbacks and
  // event handlers), mirroring the App shell's data-loading pattern.
  const fetchFleet = useCallback(
    () =>
      fetch('/api/energy/equipment', { headers: { Accept: 'application/json' } }).then(
        (response) => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`)
          return response.json()
        },
      ),
    [],
  )

  const reload = useCallback(
    () =>
      fetchFleet()
        .then((next) => {
          setFleet(next)
          setOffline(false)
        })
        .catch(() => setOffline(true)),
    [fetchFleet],
  )

  useEffect(() => {
    let stale = false
    fetchFleet()
      .then((next) => {
        if (stale) return
        setFleet(next)
        setOffline(false)
      })
      .catch(() => {
        if (!stale) setOffline(true)
      })
    return () => {
      stale = true
    }
  }, [fetchFleet])

  const analyze = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await postJson('/api/energy/analyze'))
      await reload()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [reload])

  const toggle = useCallback(
    async (item, isOn) => {
      setBusy(true)
      setError(null)
      try {
        await postJson(`/api/energy/equipment/${item.id}/toggle`, { is_on: isOn })
        await reload()
      } catch (err) {
        setError(t('energy.switchFailed', { msg: err.message }))
      } finally {
        setBusy(false)
      }
    },
    [reload, t],
  )

  const summary = fleet?.summary
  const shownItems = result?.equipment ?? fleet?.equipment ?? []

  return (
    <div className="page">
      <PageHeader
        eyebrow={t('energy.eyebrow')}
        title={t('nav.energy')}
        description={t('energy.descFull')}
      />

      <div className="tile-grid section-gap">
        <div className="tile">
          <p className="tile__label">{t('energy.tile.solar')}</p>
          <p className="tile__value">{formatNumber(solar)} kWh</p>
          <p className="tile__meta">{t('energy.meta.total7')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('energy.tile.grid')}</p>
          <p className="tile__value">{formatNumber(grid)} kWh</p>
          <p className="tile__meta">{t('energy.meta.total7')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('energy.tile.pump')}</p>
          <p className="tile__value">{formatNumber(pump)} kWh</p>
          <p className="tile__meta">{t('energy.meta.total7')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('energy.tile.saving')}</p>
          <p className="tile__value">
            ~{summary?.total_savings_kwh_estimate ?? '—'} kWh
          </p>
          <p className="tile__meta">{t('energy.tile.savingMeta')}</p>
        </div>
      </div>

      <div className="section-gap">
        <Panel
          title={t('energy.equipPanel')}
          subtitle={t('energy.equipPanel.sub')}
          action={
            <button type="button" className="btn btn--primary" onClick={analyze} disabled={busy}>
              {busy && !result ? t('energy.analyzing') : t('energy.analyze')}
            </button>
          }
        >
          {offline && <p className="empty">{t('energy.offlineNote')}</p>}
          {error && (
            <p className="form-error">{t('energy.analysisFailed', { msg: error })}</p>
          )}

          {shownItems.length > 0 && (
            <div className="cards" style={{ marginBottom: 0 }}>
              {shownItems.map((item) => (
                <EquipmentCard key={item.equipment} item={item} busy={busy} onToggle={toggle} />
              ))}
            </div>
          )}
        </Panel>
      </div>

      {result && (
        <div className="section-gap">
          <Panel
            title={t('energy.recoPanel')}
            action={<span className="badge badge--neutral">{t('common.simulated')}</span>}
          >
            <p className="analysis__why">
              <strong>{result.summary.recommendation}</strong>
            </p>
            <p className="analysis__caveat">
              {t('energy.caveat', { note: result.summary.note })}
            </p>
            {result.alerts_created.length > 0 && (
              <p className="analysis__caveat">
                {result.alerts_created.length > 1
                  ? t('energy.raisedMany', { n: result.alerts_created.length })
                  : t('energy.raisedOne')}
              </p>
            )}
            <div className="alert-list" style={{ marginTop: 8 }}>
              {shownItems
                .flatMap((item) =>
                  item.findings
                    .filter((f) => f.issue !== 'normal')
                    .map((f) => ({ ...f, equipment: item.equipment })),
                )
                .map((f) => (
                  <div className="alert-row" key={`${f.equipment}-${f.issue}`}>
                    <span className={`badge badge--${SEVERITY_TONE[f.severity] ?? 'neutral'}`}>
                      {t(`engine.issue.${f.issue}`)}
                    </span>
                    <div className="alert-row__body">
                      <p className="alert-row__title">{f.equipment}</p>
                      <p className="alert-row__msg">{f.explanation}</p>
                      <p className="alert-row__meta">
                        <span className="tag">
                          {t('energy.actionTag', { text: f.action })}
                        </span>
                        {f.savings_kwh_estimate != null && (
                          <span className="tag">
                            {t('energy.savingTag', { kwh: f.savings_kwh_estimate })}
                          </span>
                        )}
                      </p>
                    </div>
                  </div>
                ))}
            </div>
          </Panel>
        </div>
      )}

      <div className="section-gap">          <Panel title={t('panel.energy')} subtitle={t('panel.energy.sub')}>
            <BarChart
              rows={series.map((d) => ({ label: formatDay(d.day), ...d }))}
              series={[
                { key: 'kwh_solar', label: t('legend.solar'), color: 'green' },
                { key: 'kwh_grid', label: t('legend.grid'), color: 'blue' },
                { key: 'pump_kwh', label: t('legend.pump'), color: 'amber' },
              ]}
              unit=" kWh"
              label={t('chart.dailyEnergy')}
              height={230}
            />
          </Panel>
      </div>

      <div className="section-gap">          <Panel title={t('energy.tablePanel')} subtitle={t('energy.tablePanel.sub')} flush>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('table.day')}</th>
                    <th>{t('table.solar')}</th>
                    <th>{t('table.grid')}</th>
                    <th>{t('table.pump')}</th>
                    <th>{t('table.totalDraw')}</th>
                  </tr>
                </thead>
              <tbody>
                {series.map((day) => (
                  <tr key={day.day}>
                    <td>{formatDay(day.day)}</td>
                    <td className="tnum">{day.kwh_solar}</td>
                    <td className="tnum">{day.kwh_grid}</td>
                    <td className="tnum">{day.pump_kwh}</td>
                    <td className="tnum">{day.kwh_grid + day.pump_kwh}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <ScopeNote>{t('energy.scopeNote')}</ScopeNote>
    </div>
  )
}
