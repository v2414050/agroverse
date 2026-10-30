/**
 * The seven navigation sections of KrishiSync AI.
 * Kept in one place so the sidebar and the app shell agree on ids/labels.
 */
export const NAV_SECTIONS = [
  { id: 'dashboard', label: 'Dashboard', icon: 'grid' },
  { id: 'farm', label: 'My Farm', icon: 'barn' },
  { id: 'irrigation', label: 'Irrigation', icon: 'droplet' },
  { id: 'energy', label: 'Energy Optimization', icon: 'bolt' },
  { id: 'crops', label: 'Crop Advisor', icon: 'sprout' },
  { id: 'weather', label: 'Weather & Soil', icon: 'cloud' },
  { id: 'alerts', label: 'Alerts', icon: 'bell' },
  { id: 'settings', label: 'Settings', icon: 'gear' },
]

export const SECTION_IDS = NAV_SECTIONS.map((s) => s.id)
