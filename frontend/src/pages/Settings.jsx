import Panel from '../components/Panel.jsx'
import PageHeader, { ScopeNote } from './PageHeader.jsx'
import { THRESHOLDS } from '../data/demo.js'
import { useLang } from '../i18n.jsx'

export default function Settings({ data, lastSync }) {
  const { lang, setLang, t } = useLang()
  const profile = data.farm.farm
  const online = data.source === 'api'

  return (
    <div className="page">
      <PageHeader
        eyebrow={t('settings.eyebrow')}
        title={t('settings.title')}
        description={t('settings.desc')}
      />

      <Panel title={t('panel.language')} subtitle={t('panel.language.sub')}>
        <div className="scenario-row">
          <button
            type="button"
            className={`btn btn--ghost${lang === 'en' ? ' is-active' : ''}`}
            aria-pressed={lang === 'en'}
            onClick={() => setLang('en')}
            lang="en"
          >
            English
          </button>
          <button
            type="button"
            className={`btn btn--ghost${lang === 'hi' ? ' is-active' : ''}`}
            aria-pressed={lang === 'hi'}
            onClick={() => setLang('hi')}
            lang="hi"
          >
            हिन्दी
          </button>
        </div>
        <p className="analysis__caveat">{t('settings.langNote')}</p>
      </Panel>

      <div className="section-gap">
        <Panel title={t('settings.data')} subtitle="Runtime state of this session">
          <dl className="def-list">
            <div>
              <dt>{t('settings.dataSource')}</dt>
              <dd>
                {online ? t('settings.dataSourceApi') : t('settings.dataSourceLocal')}
              </dd>
            </div>
            <div>
              <dt>{t('settings.backend')}</dt>
              <dd>{online ? t('settings.connected') : t('settings.disconnected')}</dd>
            </div>
            <div>
              <dt>{t('settings.apiBase')}</dt>
              <dd>/api (proxied to :8000)</dd>
            </div>
            <div>
              <dt>{t('settings.lastRefresh')}</dt>
              <dd>{lastSync ? lastSync.toLocaleTimeString() : t('settings.notYet')}</dd>
            </div>
            <div>
              <dt>{t('settings.storage')}</dt>
              <dd>SQLite · backend/krishisync.db</dd>
            </div>
            <div>
              <dt>{t('settings.sensors')}</dt>
              <dd>{t('settings.sensorsNone')}</dd>
            </div>
          </dl>
        </Panel>
      </div>

      <div className="section-gap">
        <Panel title={t('panel.thresholds')} subtitle={t('panel.thresholds.sub')}>
          <dl className="def-list">
            <div>
              <dt>{t('settings.moistureTarget')}</dt>
              <dd>{THRESHOLDS.moisture_target}%</dd>
            </div>
            <div>
              <dt>{t('settings.irrigationTrigger')}</dt>
              <dd>{t('settings.below', { value: THRESHOLDS.irrigation })}</dd>
            </div>
            <div>
              <dt>{t('settings.healthFlag')}</dt>
              <dd>{t('settings.below', { value: 70 })}</dd>
            </div>
            <div>
              <dt>{t('settings.farm')}</dt>
              <dd>{profile?.name ?? '—'}</dd>
            </div>
          </dl>
        </Panel>
      </div>

      <ScopeNote>{t('settings.deferredNote')}</ScopeNote>
    </div>
  )
}
