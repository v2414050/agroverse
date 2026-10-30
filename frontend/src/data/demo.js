/**
 * Bundled demonstration data.
 *
 * This mirrors the exact JSON shape returned by the FastAPI backend so the
 * UI can render even when `backend/` is not running. It is synthetic data —
 * never a live sensor reading.
 */

const DEMO_NOTE =
  'Demonstration data only — no live sensors are connected in this build.'

const day = (n) => {
  const d = new Date(Date.now() - n * 86400000)
  return d.toISOString().slice(0, 10)
}

const hour = (n) => {
  const d = new Date(Date.now() - n * 3600000)
  return d.toISOString().slice(0, 16)
}

const FARM = {
  id: 1,
  name: 'Demo Green Valley Farm',
  location: 'Nashik, Maharashtra (demo location)',
  area_hectares: 12.5,
  soil_type: 'Loamy',
  latitude: 19.9975,
  longitude: 73.7898,
}

// name, crop, variety, stage, health, area ha, moisture %, zone
const PLOT_ROWS = [
  ['North Field', 'Wheat', 'HD-3086', 'Tillering', 88, 4.0, 41.0, 'Zone A'],
  ['East Field', 'Tomato', 'Abhilash', 'Flowering', 76, 2.5, 28.0, 'Zone B'],
  ['South Field', 'Sugarcane', 'Co-86032', 'Grand Growth', 92, 4.5, 55.0, 'Zone C'],
  ['West Field', 'Cotton', 'Bt-Hybrid', 'Squaring', 69, 1.5, 33.0, 'Zone A'],
]

const PLOTS = PLOT_ROWS.map(
  ([name, crop, crop_variety, growth_stage, health_pct, area_hectares, soil_moisture_pct, irrigation_zone], i) => ({
    id: i + 1,
    farm_id: 1,
    name,
    crop,
    crop_variety,
    growth_stage,
    health_pct,
    area_hectares,
    soil_moisture_pct,
    irrigation_zone,
  }),
)

const MOISTURE_TARGET = 40
const IRRIGATION_THRESHOLD = 35

/* 48 hourly readings per plot (two days), oldest first — same drift as seed.py */
const readings = []
for (let plotId = 1; plotId <= PLOTS.length; plotId += 1) {
  const base = PLOTS[plotId - 1].soil_moisture_pct
  for (let h = 48; h >= 1; h -= 1) {
    const drift = ((h % 12) - 6) * 1.5
    readings.push({
      plot_id: plotId,
      recorded_at: hour(h),
      soil_moisture_pct: Math.round(Math.max(12, Math.min(70, base + drift)) * 10) / 10,
      temperature_c: Math.round((24 + ((h * 0.35) % 12)) * 10) / 10,
      humidity_pct: Math.round((45 + ((h * 1.7) % 35)) * 10) / 10,
      rainfall_mm: h % 24 === 0 ? 2.4 : 0,
    })
  }
}

/* Seven days of water use per plot */
const plotTargets = [9500, 6200, 14800, 4100]
const waterMap = new Map()
for (let plotId = 1; plotId <= PLOTS.length; plotId += 1) {
  const target = plotTargets[plotId - 1]
  for (let d = 7; d >= 1; d -= 1) {
    const factor = 1 + (((plotId * 7 + d) % 5) - 2) * 0.09
    const key = day(d - 1)
    const bucket = waterMap.get(key) || { day: key, used: 0, target: 0 }
    bucket.used += Math.round(target * factor)
    bucket.target += target
    waterMap.set(key, bucket)
  }
}
const water = [...waterMap.values()].sort((a, b) => a.day.localeCompare(b.day))

/* Seven days of farm-level energy in kWh */
const energy = []
for (let d = 7; d >= 1; d -= 1) {
  energy.push({
    day: day(d - 1),
    kwh_solar: 38 + ((d * 5) % 14),
    kwh_grid: 22 + ((d * 3) % 11),
    pump_kwh: 19 + ((d * 7) % 13),
  })
}

const ALERTS = [
  {
    id: 1,
    created_at: hour(2),
    severity: 'critical',
    category: 'irrigation',
    title: 'East Field soil moisture below threshold',
    message:
      'East Field (Tomato) is at 28% moisture, under the 35% target. Schedule a 35-minute drip cycle in the evening to avoid evaporation loss.',
    acknowledged: 0,
  },
  {
    id: 2,
    created_at: hour(6),
    severity: 'warning',
    category: 'energy',
    title: 'Pump running during peak tariff window',
    message:
      'Zone B pump drew 6 kWh between 14:00-17:00 (peak tariff). Shifting this cycle to 19:00 could save an estimated 18% on pumping cost.',
    acknowledged: 0,
  },
  {
    id: 3,
    created_at: hour(20),
    severity: 'warning',
    category: 'crop',
    title: 'West Field crop health dipped below 70%',
    message:
      'West Field (Cotton) health index is 69%. Inspect for bollworm pressure and check nitrogen levels at the next field walk.',
    acknowledged: 0,
  },
  {
    id: 4,
    created_at: hour(30),
    severity: 'info',
    category: 'weather',
    title: 'Rain expected within 48 hours',
    message:
      'Demo weather feed shows a 60% chance of 8-12 mm rain. Consider skipping the next Zone A cycle to avoid waterlogging.',
    acknowledged: 0,
  },
  {
    id: 5,
    created_at: hour(52),
    severity: 'info',
    category: 'irrigation',
    title: 'Zone C irrigation completed',
    message:
      'South Field (Sugarcane) cycle finished: 14,200 L applied over 55 minutes. Within the daily target band.',
    acknowledged: 1,
  },
]

const latestMoisture = readings.slice(-PLOTS.length)

/* Crop-advisor fallback (mirrors the API shape; season from the calendar) */
const SEASON_LABELS = {
  kharif: 'Kharif (Jun-Oct, monsoon)',
  rabi: 'Rabi (Nov-Mar, winter)',
  zaid: 'Zaid (Apr-Jun, summer)',
}
const month = new Date().getMonth() + 1
const seasonKey =
  month >= 6 && month <= 10 ? 'kharif' : month >= 11 || month <= 3 ? 'rabi' : 'zaid'
const DEMO_CROP_ADVISOR = {
  season: seasonKey,
  season_label: SEASON_LABELS[seasonKey],
  source: 'bundled demo fallback (backend offline)',
  provisional: true,
  missing: [
    'Seasonal rainfall + irrigation access not provided.',
    'N/P/K measurements not provided.',
    'Field slope not provided.',
  ],
  top: [
    { crop: 'Cotton', score: 96, verdict_label: 'Recommended', provisional: true },
    { crop: 'Maize', score: 94, verdict_label: 'Recommended', provisional: true },
    { crop: 'Sugarcane', score: 88, verdict_label: 'Recommended', provisional: true },
  ],
  summary: {
    count: 10,
    recommended_count: 3,
    top_crop: 'Cotton',
    top_score: 96,
    top_verdict: 'Recommended',
    provisional: true,
    note:
      'Scores are a transparent rule-based fit against the demo requirement dataset — a suitability indicator, not a yield prediction or guarantee.',
  },
}

export const DEMO_DASHBOARD = {
  demo_data: true,
  demo_note: DEMO_NOTE,
  farm: FARM,
  soil_moisture: {
    average_pct:
      Math.round(
        (latestMoisture.reduce((sum, r) => sum + r.soil_moisture_pct, 0) /
          latestMoisture.length) *
          10,
      ) / 10,
    target_pct: MOISTURE_TARGET,
    series: readings.slice(-24),
    per_plot: PLOTS,
  },
  water_usage: {
    total_litres: water.reduce((sum, w) => sum + w.used, 0),
    target_litres: water.reduce((sum, w) => sum + w.target, 0),
    series: water,
  },
  energy: { latest: energy[energy.length - 1], series: energy },
  crops: PLOTS,
  crop_advisor: DEMO_CROP_ADVISOR,
  irrigation: {
    zones: PLOTS.map((p) => ({
      zone: p.irrigation_zone,
      plot: p.name,
      soil_moisture_pct: p.soil_moisture_pct,
      status: p.soil_moisture_pct < IRRIGATION_THRESHOLD ? 'needs_water' : 'ok',
    })),
  },
  alerts: ALERTS,
}

export const DEMO_FARM = {
  demo_data: true,
  demo_note: DEMO_NOTE,
  farm: FARM,
  plots: PLOTS,
}

export const DEMO_ALERTS = {
  demo_data: true,
  demo_note: DEMO_NOTE,
  alerts: ALERTS,
}

export const DEMO_NOTE_TEXT = DEMO_NOTE
export const THRESHOLDS = { moisture_target: MOISTURE_TARGET, irrigation: IRRIGATION_THRESHOLD }
