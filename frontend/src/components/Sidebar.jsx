import Icon from './Icon.jsx'
import { NAV_SECTIONS } from '../data/nav.js'
import { useLang } from '../i18n.jsx'

/**
 * Primary navigation. Selecting an item writes the URL hash so the browser
 * back/forward buttons keep working without a router dependency.
 * Labels follow the selected language (English / हिन्दी).
 */
export default function Sidebar({ active, onNavigate, open, onClose, alertCount }) {
  const { t } = useLang()

  return (
    <>
      {open && (
        <button type="button" className="scrim" aria-label={t('nav.close')} onClick={onClose} />
      )}

      <aside className={`sidebar${open ? ' is-open' : ''}`} id="app-sidebar">
        <button
          type="button"
          className="sidebar__close"
          onClick={onClose}
          aria-label={t('nav.close')}
        >
          <Icon name="close" size={18} />
        </button>

        <p className="nav__section">{t('nav.section')}</p>
        <nav aria-label="Main navigation">
          <ul className="nav__list">
            {NAV_SECTIONS.map((section) => {
              const isActive = section.id === active
              const showBadge = section.id === 'alerts' && alertCount > 0

              return (
                <li key={section.id}>
                  <a
                    href={`#/${section.id}`}
                    className={`nav__btn${isActive ? ' is-active' : ''}`}
                    aria-current={isActive ? 'page' : undefined}
                    onClick={(event) => {
                      event.preventDefault()
                      onNavigate(section.id)
                    }}
                  >
                    <Icon name={section.icon} size={18} />
                    <span>{t(`nav.${section.id}`)}</span>
                    {showBadge && <span className="nav__badge">{alertCount}</span>}
                  </a>
                </li>
              )
            })}
          </ul>
        </nav>

        <p className="sidebar__note">
          <strong>{t('sidebar.noteTitle')}</strong> {t('sidebar.noteBody')}
        </p>
      </aside>
    </>
  )
}
