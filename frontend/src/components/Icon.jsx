/**
 * Tiny inline icon set — no icon package required.
 * Every icon is a 24x24 stroke drawing that inherits currentColor.
 */

const PATHS = {
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  barn: (
    <>
      <path d="M3 10.5 12 3.5l9 7" />
      <path d="M5 9.7V20.5h14V9.7" />
      <path d="M9.5 20.5v-5.2h5v5.2" />
    </>
  ),
  droplet: <path d="M12 3 6.8 8.4a7.3 7.3 0 1 0 10.4 0Z" />,
  bolt: <path d="M13.2 2.5 4.8 13.8h6.1L10.3 21.5l8.4-11.3h-6.1Z" />,
  sprout: (
    <>
      <path d="M11.5 20.5A7.5 7.5 0 0 1 4 13c0-6.4 7.2-9.5 16.5-9.5 0 9.3-4 17-9 17Z" />
      <path d="M4.5 20.5c1.9-4.9 5.2-8.3 9.3-10.4" />
    </>
  ),
  bell: (
    <>
      <path d="M18 8.5a6 6 0 1 0-12 0c0 6.5-2.5 7.5-2.5 7.5h17S18 15 18 8.5Z" />
      <path d="M10.2 19.5a2.1 2.1 0 0 0 3.6 0" />
    </>
  ),
  gear: (
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 2.8v2.4M12 18.8v2.4M4.5 4.5l1.7 1.7M17.8 17.8l1.7 1.7M2.8 12h2.4M18.8 12h2.4M4.5 19.5l1.7-1.7M17.8 6.2l1.7-1.7" />
    </>
  ),
  gauge: (
    <>
      <path d="M4 17.5a9 9 0 1 1 16 0" />
      <path d="M12 16.5 16.5 10" />
      <circle cx="12" cy="17.5" r="1.4" />
    </>
  ),
  dropcount: (
    <>
      <path d="M12 3.2 7.6 7.6a6 6 0 1 0 8.8 0Z" />
      <path d="M12 10.5v4.2M10 12.6h4" />
    </>
  ),
  leafCheck: (
    <>
      <path d="M20 4c0 8-4.5 13-10.5 13-1.4 0-2.7-.3-3.9-.8C6.1 10.2 10.6 5.2 20 4Z" />
      <path d="m8.5 17.5 2.5 2.5 4.5-5" />
    </>
  ),
  alert: (
    <>
      <path d="M12 4.5 21 19.5H3Z" />
      <path d="M12 10v4M12 16.6v.1" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  refresh: (
    <>
      <path d="M20 12a8 8 0 1 1-2.6-5.9" />
      <path d="M20.5 4v4.5H16" />
    </>
  ),
  pin: (
    <>
      <path d="M19.5 10.5c0 5.8-7.5 11-7.5 11s-7.5-5.2-7.5-11a7.5 7.5 0 0 1 15 0Z" />
      <circle cx="12" cy="10.3" r="2.7" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5M12 7.8v.1" />
    </>
  ),
  cloud: <path d="M17 18H7a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 10.5 4 4 0 0 1 17 18Z" />,
}

export default function Icon({ name, size = 18 }) {
  const path = PATHS[name]
  if (!path) return null

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {path}
    </svg>
  )
}
