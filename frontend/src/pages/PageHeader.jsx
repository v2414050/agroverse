import Icon from '../components/Icon.jsx'

/**
 * Reusable page header: eyebrow, title and one-line description.
 */
export default function PageHeader({ eyebrow, title, description }) {
  return (
    <header className="page__head">
      <p className="page__eyebrow">{eyebrow}</p>
      <h1 className="page__title">{title}</h1>
      <p className="page__sub">{description}</p>
    </header>
  )
}

/**
 * Small helper for the read-only "coming next step" notes shown on the
 * section pages that are not implemented yet.
 */
export function ScopeNote({ children }) {
  return (
    <p className="note">
      <Icon name="info" size={16} />
      <span>{children}</span>
    </p>
  )
}
