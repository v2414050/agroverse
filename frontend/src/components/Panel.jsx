import './components.css'

/**
 * Reusable white panel used to group page content.
 */
export default function Panel({ title, subtitle, action, flush = false, children }) {
  return (
    <section className="panel">
      {(title || action) && (
        <header className="panel__head">
          <div>
            {title && <h2 className="panel__title">{title}</h2>}
            {subtitle && <p className="panel__sub">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={flush ? 'panel__body panel__body--flush' : 'panel__body'}>
        {children}
      </div>
    </section>
  )
}
