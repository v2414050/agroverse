import { useMemo, useState } from 'react'
import Panel from '../components/Panel.jsx'
import Icon from '../components/Icon.jsx'
import PageHeader from './PageHeader.jsx'
import { useLang } from '../i18n.jsx'
import { formatDateTime, formatNumber } from '../lib/format.js'

const FILTERS = ['all', 'active', 'done']

// English item strings reported by the backend → dictionary keys.
const ITEM_KEY = {
  'soil pH': 'soilPh',
  'soil type': 'soilType',
  'seasonal rainfall': 'rainfall',
  'irrigation access': 'irrigation',
  'soil NPK test': 'npk',
  'field slope': 'slope',
  temperature: 'temperature',
  season: 'season',
  'farm profile': 'farmProfile',
}

const round1 = (v) => (typeof v === 'number' ? Math.round(v * 10) / 10 : v)

export default function Alerts({ data, online, onAlertsChanged }) {
  const { t } = useLang()
  const alerts = data.alerts.alerts

  const [filter, setFilter] = useState('all')
  // Optimistic local acknowledgements (also the offline-mode store).
  const [acked, setAcked] = useState(() => new Set())
  const [busyId, setBusyId] = useState(null)
  const [syncing, setSyncing] = useState(false)
  const [note, setNote] = useState(null) // { tone: 'ok' | 'err', text }
  const [error, setError] = useState(null)

  // Translate a key, but keep the English fallback when the key is missing.
  const tr = (key, fallback, vars) => {
    const value = t(key, vars)
    return value === key ? fallback : value
  }

  // Rebuild title/message/action from the stored params when the alert
  // carries an issue code — so engine alerts follow the chosen language.
  const localize = (alert) => {
    const base = { title: alert.title, message: alert.message, action: alert.action }
    const p = alert.params ?? {}
    switch (alert.issue) {
      case 'low_moisture': {
        const vars = {
          plot: p.plot,
          zone: p.zone,
          moisture: round1(p.moisture),
          target: round1(p.target),
        }
        return {
          ...base,
          title: tr('alert.low_moisture.title', base.title, vars),
          message: tr(
            p.critical
              ? 'alert.low_moisture.descCritical'
              : 'alert.low_moisture.descWarn',
            base.message,
            vars,
          ),
          action: p.action_code
            ? tr(`irrig.action.${p.action_code}`, base.action)
            : base.action,
        }
      }
      case 'excessive_moisture': {
        const vars = {
          plot: p.plot,
          zone: p.zone,
          moisture: round1(p.moisture),
          saturation: round1(p.saturation),
        }
        return {
          ...base,
          title: tr('alert.excessive_moisture.title', base.title, vars),
          message: tr('alert.excessive_moisture.desc', base.message, vars),
          action: tr('alert.excessive_moisture.action', base.action, vars),
        }
      }
      case 'unnecessary_irrigation': {
        const vars = {
          zone: p.zone,
          hours: p.hours_ago,
          status: tr(`engine.status.${p.status}`, p.status),
        }
        return {
          ...base,
          title: tr('alert.unnecessary_irrigation.title', base.title, vars),
          message: tr('alert.unnecessary_irrigation.desc', base.message, vars),
          action: tr('alert.unnecessary_irrigation.action', base.action, vars),
        }
      }
      case 'unnecessary_equipment': {
        const issue = String(p.finding ?? '')
          .split('_')
          .join(' ')
        const vars = {
          equipment: p.equipment,
          issue: tr(`engine.issue.${p.finding}`, issue),
        }
        return {
          ...base,
          title: tr('alert.unnecessary_equipment.title', base.title, vars),
        }
      }
      case 'missing_farm_info': {
        if (!p.registered) {
          return {
            ...base,
            title: tr(
              'alert.missing_farm_info.noFarm.title',
              base.title,
            ),
            message: tr('alert.missing_farm_info.noFarm.desc', base.message),
            action: tr('alert.missing_farm_info.noFarm.action', base.action),
          }
        }
        const items = (p.items ?? [])
          .map((item) => t(`item.${ITEM_KEY[item] ?? item}`))
          .join(', ')
        const vars = { name: p.name, items }
        return {
          ...base,
          title: tr('alert.missing_farm_info.title', base.title, vars),
          message: tr('alert.missing_farm_info.desc', base.message, vars),
          action: tr('alert.missing_farm_info.action', base.action, vars),
        }
      }
      case 'crop_limitation': {
        const vars = {
          crop: p.crop,
          score: p.score,
          verdict: tr(`verdict.${p.verdict}`, p.verdict_label),
          limitation: p.first_limit,
        }
        return {
          ...base,
          title: tr('alert.crop_limitation.title', base.title, vars),
          message: tr('alert.crop_limitation.desc', base.message, vars),
        }
      }
      default:
        return base
    }
  }

  const isAcked = (alert) => Boolean(alert.acknowledged) || acked.has(alert.id)
  const active = alerts.filter((a) => !isAcked(a))
  const countOf = (severity) => active.filter((a) => a.severity === severity).length

  const shown = useMemo(() => {
    if (filter === 'active') return alerts.filter((a) => !isAcked(a))
    if (filter === 'done') return alerts.filter((a) => isAcked(a))
    return alerts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alerts, filter, acked])

  async function acknowledge(alert) {
    setError(null)
    setBusyId(alert.id)

    if (!online || !alert.id) {
      // Backend offline — keep the acknowledgement for this session only.
      setAcked((current) => new Set(current).add(alert.id))
      setBusyId(null)
      return
    }

    try {
      const response = await fetch(`/api/alerts/${alert.id}/ack`, { method: 'POST' })
      if (!response.ok) throw new Error(`ack responded ${response.status}`)
      setAcked((current) => new Set(current).add(alert.id))
      onAlertsChanged?.()
    } catch {
      setError(t('alerts.ackFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function recheckEngines() {
    setSyncing(true)
    setNote(null)
    setError(null)
    try {
      const response = await fetch('/api/alerts/sync', { method: 'POST' })
      if (!response.ok) throw new Error(`sync responded ${response.status}`)
      const body = await response.json()
      const raised = body.created_count ?? 0
      setNote({
        tone: 'ok',
        text:
          raised > 0 ? t('alerts.syncNew', { n: raised }) : t('alerts.syncNone'),
      })
      onAlertsChanged?.()
    } catch {
      setNote({ tone: 'err', text: t('alerts.recheckFailed') })
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow={t('alerts.eyebrow')}
        title={t('alerts.title')}
        description={t('alerts.desc')}
      />

      <div className="tile-grid section-gap">
        <div className="tile">
          <p className="tile__label">{t('alerts.tile.active')}</p>
          <p className="tile__value">{active.length}</p>
          <p className="tile__meta">{t('alerts.meta.active')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('alerts.tile.critical')}</p>
          <p className="tile__value">{countOf('critical')}</p>
          <p className="tile__meta">{t('alerts.meta.critical')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('alerts.tile.warnings')}</p>
          <p className="tile__value">{countOf('warning')}</p>
          <p className="tile__meta">{t('alerts.meta.warnings')}</p>
        </div>
        <div className="tile">
          <p className="tile__label">{t('alerts.tile.logged')}</p>
          <p className="tile__value">{formatNumber(alerts.length)}</p>
          <p className="tile__meta">{t('alerts.meta.logged')}</p>
        </div>
      </div>

      <div className="section-gap">
        <Panel
          title={t('panel.history')}
          subtitle={t('panel.history.sub')}
          action={
            online ? (
              <button
                type="button"
                className="btn"
                onClick={recheckEngines}
                disabled={syncing}
              >
                <Icon name="refresh" size={15} />
                {syncing ? t('alerts.rechecking') : t('alerts.recheck')}
              </button>
            ) : (
              <span className="tag">{t('alerts.enginesOffline')}</span>
            )
          }
          flush
        >
          <div className="alerts__bar">
            {FILTERS.map((id) => (
              <button
                key={id}
                type="button"
                className={`btn btn--ghost${filter === id ? ' is-active' : ''}`}
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
              >
                {t(`alerts.filter.${id}`)}
              </button>
            ))}
            <span className="alerts__count">
              {t('alerts.showing', {
                shown: formatNumber(shown.length),
                total: formatNumber(alerts.length),
              })}
            </span>
          </div>

          {note && (
            <p className={`alerts__note${note.tone === 'err' ? ' is-error' : ''}`}>
              {note.text}
            </p>
          )}
          {error && <p className="form-error">{error}</p>}
          {!online && <p className="alerts__note">{t('alerts.offlineNote')}</p>}

          {shown.length === 0 ? (
            <p className="empty">{t(`alerts.empty${filter === 'all' ? 'All' : filter === 'active' ? 'Active' : 'Done'}`)}</p>
          ) : (
            <div className="alert-list">
              {shown.map((alert) => {
                const content = localize(alert)
                return (
                  <article className="alert-row" key={alert.id ?? alert.title}>
                    <span className={`badge badge--${alert.severity}`}>
                      {t(`alerts.sev.${alert.severity}`)}
                    </span>
                    <div className="alert-row__body">
                      <div className="alert-row__head">
                        <p className="alert-row__title">{content.title}</p>
                        {isAcked(alert) ? (
                          <span className="tag">
                            <Icon name="leafCheck" size={13} /> {t('alerts.acked')}
                          </span>
                        ) : (
                          <button
                            type="button"
                            className="btn btn--ghost alert-row__ack"
                            onClick={() => acknowledge(alert)}
                            disabled={busyId === alert.id}
                          >
                            {busyId === alert.id ? t('alerts.acking') : t('alerts.ack')}
                          </button>
                        )}
                      </div>

                      <p className="alert-row__msg">{content.message}</p>

                      {content.action && (
                        <p className="alert-row__action">
                          <Icon name="leafCheck" size={15} />
                          <span>
                            <strong>{t('alerts.recAction')}</strong>{' '}
                            {content.action}
                          </span>
                        </p>
                      )}

                      <p className="alert-row__meta">
                        <span className="tag">
                          {tr(`alerts.cat.${alert.category}`, alert.category)}
                        </span>
                        {alert.related && (
                          <span className="tag">
                            <Icon name="pin" size={12} /> {alert.related}
                          </span>
                        )}
                        <span>{formatDateTime(alert.created_at)}</span>
                        <span>·</span>
                        <span>
                          {isAcked(alert) ? t('alerts.acked') : t('alerts.status.active')}
                        </span>
                      </p>
                    </div>
                  </article>
                )
              })}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
