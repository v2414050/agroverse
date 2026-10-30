import Panel from '../components/Panel.jsx'
import PageHeader, { ScopeNote } from './PageHeader.jsx'
import { useLang } from '../i18n.jsx'
import { percent } from '../lib/format.js'

function HealthBadge({ value }) {
  const tone = value >= 80 ? 'ok' : value >= 70 ? 'warning' : 'critical'
  return <span className={`badge badge--${tone}`}>{value}%</span>
}

function MoistureBadge({ value }) {
  const tone = value >= 40 ? 'ok' : value >= 35 ? 'warning' : 'critical'
  return <span className={`badge badge--${tone}`}>{percent(value)}</span>
}

export default function MyFarm({ data }) {
  const { t } = useLang()
  const { farm } = data
  const profile = farm.farm
  const plots = farm.plots ?? []

  const totalArea = plots.reduce((sum, p) => sum + (p.area_hectares || 0), 0)
  const crops = [...new Set(plots.map((p) => p.crop))]

  return (
    <div className="page">
      <PageHeader
        eyebrow={t('farm.eyebrow')}
        title={t('farm.title')}
        description={t('farm.desc')}
      />

      <Panel
        title={profile ? profile.name : t('farm.noFarm')}
        subtitle={t('farm.profileRecord')}
        action={<span className="badge badge--ok">{t('farm.demoRecord')}</span>}
      >
        <dl className="def-list">
          <div>
            <dt>{t('farm.label.location')}</dt>
            <dd>{profile?.location ?? '—'}</dd>
          </div>
          <div>
            <dt>{t('farm.label.area')}</dt>
            <dd>{profile?.area_hectares ?? '—'} ha</dd>
          </div>
          <div>
            <dt>{t('farm.label.soilType')}</dt>
            <dd>{profile?.soil_type ?? '—'}</dd>
          </div>
          <div>
            <dt>{t('farm.label.plots')}</dt>
            <dd>{plots.length}</dd>
          </div>
          <div>
            <dt>{t('farm.label.crops')}</dt>
            <dd>{crops.join(', ') || '—'}</dd>
          </div>
          <div>
            <dt>{t('farm.label.coords')}</dt>
            <dd>
              {profile
                ? `${profile.latitude.toFixed(4)}, ${profile.longitude.toFixed(4)}`
                : '—'}
            </dd>
          </div>
        </dl>
      </Panel>

      <div className="section-gap">
        <Panel
          title={t('panel.plots')}
          subtitle={t('panel.plots.sub', { area: totalArea.toFixed(1) })}
          flush
        >
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('table.plot')}</th>
                  <th>{t('table.crop')}</th>
                  <th>{t('table.variety')}</th>
                  <th>{t('table.stage')}</th>
                  <th>{t('table.area')}</th>
                  <th>{t('table.health')}</th>
                  <th>{t('table.moisture')}</th>
                  <th>{t('table.zone')}</th>
                </tr>
              </thead>
              <tbody>
                {plots.map((plot) => (
                  <tr key={plot.id}>
                    <td>{plot.name}</td>
                    <td>{plot.crop}</td>
                    <td>{plot.crop_variety}</td>
                    <td>{plot.growth_stage}</td>
                    <td className="tnum">{plot.area_hectares} ha</td>
                    <td>
                      <HealthBadge value={plot.health_pct} />
                    </td>
                    <td>
                      <MoistureBadge value={plot.soil_moisture_pct} />
                    </td>
                    <td>{plot.irrigation_zone}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <ScopeNote>{t('farm.scopeNote')}</ScopeNote>
    </div>
  )
}
