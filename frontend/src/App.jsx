import { useCallback, useEffect, useState } from 'react'
import './App.css'
import './pages/pages.css'

import Icon from './components/Icon.jsx'
import Sidebar from './components/Sidebar.jsx'
import { SECTION_IDS } from './data/nav.js'
import { useLang } from './i18n.jsx'
import { DEMO_ALERTS, DEMO_DASHBOARD, DEMO_FARM } from './data/demo.js'

import Dashboard from './pages/Dashboard.jsx'
import MyFarm from './pages/MyFarm.jsx'
import Irrigation from './pages/Irrigation.jsx'
import Energy from './pages/Energy.jsx'
import CropAdvisor from './pages/CropAdvisor.jsx'
import Weather from './pages/Weather.jsx'
import Alerts from './pages/Alerts.jsx'
import Settings from './pages/Settings.jsx'

function readHash() {
  const id = window.location.hash.replace(/^#\/?/, '')
  return SECTION_IDS.includes(id) ? id : 'dashboard'
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`${path} responded ${response.status}`)
  return response.json()
}

/**
 * Loads the three API endpoints and falls back to the bundled demo data for
 * whichever one is unreachable. Lives outside the component so effects only
 * synchronize results instead of triggering renders directly.
 */
async function loadAll() {
  const [dashboard, farm, alerts] = await Promise.allSettled([
    fetchJson('/api/dashboard'),
    fetchJson('/api/farm'),
    fetchJson('/api/alerts'),
  ])

  const anyLive = [dashboard, farm, alerts].some((r) => r.status === 'fulfilled')

  return {
    dashboard: dashboard.status === 'fulfilled' ? dashboard.value : DEMO_DASHBOARD,
    farm: farm.status === 'fulfilled' ? farm.value : DEMO_FARM,
    alerts: alerts.status === 'fulfilled' ? alerts.value : DEMO_ALERTS,
    source: anyLive ? 'api' : 'offline',
    loading: false,
  }
}

export default function App() {
  const { lang, setLang, t } = useLang()
  const [active, setActive] = useState(readHash)
  const [navOpen, setNavOpen] = useState(false)
  const [lastSync, setLastSync] = useState(null)

  // data.source: 'api' | 'offline'
  const [data, setData] = useState({
    dashboard: DEMO_DASHBOARD,
    farm: DEMO_FARM,
    alerts: DEMO_ALERTS,
    source: 'offline',
    loading: true,
  })

  const applyData = useCallback((next) => {
    setData(next)
    setLastSync(new Date())
  }, [])

  const refresh = useCallback(() => {
    setData((current) => ({ ...current, loading: true }))
    loadAll().then(applyData)
  }, [applyData])

  useEffect(() => {
    let stale = false
    loadAll().then((next) => {
      if (!stale) applyData(next)
    })
    return () => {
      stale = true
    }
  }, [applyData])

  useEffect(() => {
    const onHashChange = () => {
      setActive(readHash())
      setNavOpen(false)
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const navigate = (id) => {
    setActive(id)
    setNavOpen(false)
    if (readHash() !== id) window.location.hash = `#/${id}`
    window.scrollTo({ top: 0 })
  }

  const open = data.source === 'api'
  const alertCount = data.alerts.alerts.filter((a) => !a.acknowledged).length

  const pages = {
    dashboard: <Dashboard data={data} />,
    farm: <MyFarm data={data} />,
    irrigation: <Irrigation data={data} />,
    energy: <Energy data={data} />,
    crops: <CropAdvisor data={data} />,
    weather: <Weather />,
    alerts: (
      <Alerts data={data} online={data.source === 'api'} onAlertsChanged={refresh} />
    ),
    settings: <Settings data={data} lastSync={lastSync} />,
  }

  return (
    <div className="app">
      <header className="app__header">
        <button
          type="button"
          className="menu-btn"
          onClick={() => setNavOpen(true)}
          aria-label={t('nav.open')}
          aria-controls="app-sidebar"
        >
          <Icon name="menu" size={18} />
        </button>

        <div className="brand">
          <span className="brand__mark">
            <Icon name="sprout" size={19} />
          </span>
          <span>
            <span className="brand__name">KrishiSync AI</span>
            <span className="brand__tag">{t('brand.tag')}</span>
          </span>
        </div>

        <div className="header__spacer" />

        <span className={`chip ${open ? 'chip--api' : 'chip--offline'}`}>
          <span className="chip__dot" />
          {data.loading
            ? t('chip.connecting')
            : open
              ? t('chip.connected')
              : t('chip.offline')}
        </span>

        <span className="chip chip--demo">{t('chip.demo')}</span>

        <div className="lang-toggle" role="group" aria-label={t('panel.language')}>
          <button
            type="button"
            className={lang === 'en' ? 'is-active' : ''}
            aria-pressed={lang === 'en'}
            onClick={() => setLang('en')}
            lang="en"
          >
            EN
          </button>
          <button
            type="button"
            className={lang === 'hi' ? 'is-active' : ''}
            aria-pressed={lang === 'hi'}
            onClick={() => setLang('hi')}
            lang="hi"
          >
            हिं
          </button>
        </div>

        <button
          type="button"
          className="icon-btn"
          onClick={refresh}
          disabled={data.loading}
          title={t('action.refresh')}
          aria-label={t('action.refresh')}
        >
          <Icon name="refresh" size={17} />
        </button>
      </header>

      <div className="app__body">
        <Sidebar
          active={active}
          onNavigate={navigate}
          open={navOpen}
          onClose={() => setNavOpen(false)}
          alertCount={alertCount}
        />

        <main className="main">
          <p className="demo-banner">
            <Icon name="alert" size={17} />
            <span>
              <strong>{t('banner.title')}</strong> {t('banner.body')}
              {data.source === 'offline' && t('banner.offline')}
            </span>
          </p>

          {pages[active]}
        </main>
      </div>
    </div>
  )
}
