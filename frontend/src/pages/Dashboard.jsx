import StatCard from '../components/StatCard.jsx'
import Panel from '../components/Panel.jsx'
import Icon from '../components/Icon.jsx'
import PageHeader, { ScopeNote } from './PageHeader.jsx'
import { useLang } from '../i18n.jsx'
import { formatDateTime, formatLitres, formatNumber, percent } from '../lib/format.js'

const MOISTURE_TONE = (value, target) => {
  if (value < 35) return 'alert'
  if (value < target) return 'warn'
  return 'ok'
}

const ADVICE_TONE = {
  DRY: 'critical',
  OPTIMAL: 'ok',
  HIGH: 'warning',
  SATURATED: 'info',
  UNKNOWN: 'neutral',
}

export default function Dashboard({ data }) {
  const { t } = useLang()
  const { dashboard, alerts } = data
  const { soil_moisture: moisture, water_usage: water, energy, crops, irrigation } =
    dashboard
  const cropAdvisor = dashboard.crop_advisor

  const target = moisture.target_pct ?? 40
  const avg = moisture.average_pct ?? 0
  const avgTone = MOISTURE_TONE(avg, target)

  const zones = irrigation.zones
  const dryZones = zones.filter((z) => z.status === 'needs_water')

  const waterPct = water.target_litres
    ? Math.round((water.total_litres / water.target_litres) * 100)
    : 0
  const waterTone = waterPct > 100 ? 'alert' : waterPct > 90 ? 'warn' : 'ok'

  const latest = energy.latest
  const grid = latest?.kwh_grid ?? 0
  const solar = latest?.kwh_solar ?? 0
  const pump = latest?.pump_kwh ?? 0
  const energyAdvice = energy.advice

  const suitable = crops.filter((c) => c.health_pct >= 70)

  const active = alerts.alerts.filter((a) => !a.acknowledged)
  const count = (severity) => active.filter((a) => a.severity === severity).length
  const breakdown = [
    count('critical') ? t('card.alerts.critical', { n: count('critical') }) : null,
    count('warning') ? t('card.alerts.warnings', { n: count('warning') }) : null,
    count('info') ? t('card.alerts.info', { n: count('info') }) : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const recent = alerts.alerts.slice(0, 3)

  const adviceZones = zones.filter((z) => z.advice)

  // Prefer the translated action code; fall back to the engine's English label.
  const adviceAction = (advice) => {
    const key = `irrig.action.${advice.action}`
    const translated = advice.action ? t(key) : key
    return translated === key ? advice.action_label : translated
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow={t('dash.eyebrow')}
        title={t('dash.title')}
        description={t('dash.desc')}
      />

      <div className="cards">
        <StatCard
          icon="droplet"
          label={t('card.soil.title')}
          value={avg}
          unit="%"
          tone={avgTone}
          sub={t('card.soil.sub', { target, plots: moisture.per_plot.length })}
          bar={avg}
        />

        <StatCard
          icon="gauge"
          label={t('card.irrig.title')}
          value={`${dryZones.length} / ${zones.length}`}
          tone={dryZones.length ? 'warn' : 'ok'}
          unit={dryZones.length ? t('card.irrig.unitDry') : t('card.irrig.unitOk')}
          sub={
            dryZones.length
              ? t('card.irrig.subDry', {
                  names: dryZones.map((z) => z.plot).join(', '),
                })
              : t('card.irrig.subOk', { total: zones.length })
          }
        />

        <StatCard
          icon="dropcount"
          label={t('card.water.title')}
          value={formatLitres(water.total_litres)}
          tone={waterTone}
          sub={t('card.water.sub', {
            pct: waterPct,
            target: formatLitres(water.target_litres),
          })}
          bar={waterPct}
        />

        <StatCard
          icon="bolt"
          label={t('card.energy.title')}
          value={pump}
          unit="kWh"
          tone={energyAdvice?.findings_count ? 'warn' : 'ok'}
          sub={
            t('card.energy.sub', { grid, solar }) +
            (energyAdvice?.findings_count
              ? t('card.energy.findings', { n: energyAdvice.findings_count })
              : '')
          }
        />

        <StatCard
          icon="leafCheck"
          label={t('card.crops.title')}
          value={`${suitable.length} / ${crops.length}`}
          tone="ok"
          unit={t('card.crops.unit')}
          sub={crops.map((c) => c.crop).join(', ')}
        />

        <StatCard
          icon="bell"
          label={t('card.alerts.title')}
          value={active.length}
          tone={count('critical') ? 'alert' : active.length ? 'warn' : 'ok'}
          unit={t('card.alerts.unit')}
          sub={
            breakdown || t('card.alerts.subOk')
          }
        />
      </div>

      <div className="panel-grid">
        <Panel
          title={t('panel.perPlot')}
          subtitle={t('panel.perPlot.sub', { target })}
        >
          <div className="bar-rows">
            {moisture.per_plot.map((plot) => {
              const tone = MOISTURE_TONE(plot.soil_moisture_pct, target)
              const toneClass = tone === 'alert' ? ' is-alert' : tone === 'warn' ? ' is-warn' : ''
              return (
                <div key={plot.id}>
                  <div className="bar-row__head">
                    <span className="bar-row__name">
                      {plot.name}
                      <span className="bar-row__crop">{plot.crop}</span>
                    </span>
                    <span className={`bar-row__value${toneClass}`}>
                      {percent(plot.soil_moisture_pct)}
                    </span>
                  </div>
                  <div className="meter">
                    <div
                      className={`meter__fill${toneClass}`}
                      style={{ width: `${plot.soil_moisture_pct}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </Panel>

        <Panel
          title={t('panel.recentAlerts')}
          subtitle={t('panel.recentAlerts.sub')}
          action={
            <span className="badge badge--neutral">
              {t('alerts.total', { n: formatNumber(alerts.alerts.length) })}
            </span>
          }
          flush
        >
          {recent.length === 0 ? (
            <p className="empty">{t('empty.alerts')}</p>
          ) : (
            <div className="alert-list">
              {recent.map((alert) => (
                <div className="alert-row" key={alert.id}>
                  <span className={`badge badge--${alert.severity}`}>
                    {t(`alerts.sev.${alert.severity}`)}
                  </span>
                  <div className="alert-row__body">
                    <p className="alert-row__title">{alert.title}</p>
                    <p className="alert-row__meta">
                      <span className="tag">
                        {t(`alerts.cat.${alert.category}`)}
                      </span>
                      <span>{formatDateTime(alert.created_at)}</span>
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {adviceZones.length > 0 && (
        <div className="section-gap">
          <Panel
            title={t('panel.irrigAdvice')}
            subtitle={t('panel.irrigAdvice.sub')}
          >
            <div className="alert-list">
              {adviceZones.map((z) => (
                <div className="alert-row" key={`${z.zone}-${z.plot}`}>
                  <span className={`badge badge--${ADVICE_TONE[z.advice.status] ?? 'neutral'}`}>
                    {t(`engine.status.${z.advice.status}`)}
                  </span>
                  <div className="alert-row__body">
                    <p className="alert-row__title">
                      {z.plot} · {z.zone} — {adviceAction(z.advice)}
                    </p>
                    <p className="alert-row__msg">{z.advice.explanation}</p>
                    <p className="alert-row__meta">
                      <span className="tag">
                        {t('panel.confidence', { level: z.advice.confidence })}
                      </span>
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      )}

      {cropAdvisor?.top?.length > 0 && (
        <div className="section-gap">
          <Panel
            title={t('panel.cropQuick')}
            subtitle={t('panel.cropQuick.sub', { season: cropAdvisor.season_label })}
            action={
              cropAdvisor.provisional ? (
                <span className="badge badge--warning">{t('badge.provisional')}</span>
              ) : (
                <span className="badge badge--ok">{t('badge.complete')}</span>
              )
            }
          >
            <div className="alert-list">
              {cropAdvisor.top.map((cropRow) => (
                <div className="alert-row" key={cropRow.crop}>
                  <span
                    className={`badge badge--${cropRow.verdict_label === 'Recommended' ? 'ok' : 'warning'}`}
                  >
                    {cropRow.score ?? '—'} / 100
                  </span>
                  <div className="alert-row__body">
                    <p className="alert-row__title">
                      {cropRow.crop} — {cropRow.verdict_label}
                    </p>
                    <p className="alert-row__meta">
                      <span className="tag">{t('tag.fitNotYield')}</span>
                      {cropRow.provisional && (
                        <span className="tag">{t('tag.provisionalShort')}</span>
                      )}
                    </p>
                  </div>
                </div>
              ))}
            </div>
            <p className="analysis__caveat">
              <strong>{t('crops.missingForFull')}</strong>{' '}
              {(cropAdvisor.missing ?? []).join(' ')}
            </p>
            <p className="analysis__caveat">{t('dash.openCropsHint')}</p>
          </Panel>
        </div>
      )}

      <ScopeNote>{t('dash.scopeNote')}</ScopeNote>

      <p className="note" style={{ marginTop: 8 }}>
        <Icon name="info" size={16} />
        <span>{t('dash.plannedNote')}</span>
      </p>
    </div>
  )
}
