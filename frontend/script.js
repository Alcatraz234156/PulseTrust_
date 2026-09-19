// PulseTrust - script.js
/* ============================================================
   PulseTrust TrustTwin — script.js
   Machine Trust Cockpit — Frontend Logic
   ============================================================ */

'use strict';

/* ╔══════════════════════════════════════════════════════════╗
   ║  1. CONFIG                                               ║
   ╚══════════════════════════════════════════════════════════╝ */
const CONFIG = {
  API_BASE:           'http://127.0.0.1:8000',
  POLL_INTERVAL_MS:   5000,
  CONNECT_TIMEOUT_MS: 6000,
  HISTORY_MAX:        200,
};

/* ╔══════════════════════════════════════════════════════════╗
   ║  2. mapBackendPayload() — FIELD NORMALISATION ONLY       ║
   ║                                                          ║
   ║  This function maps raw backend field names into the     ║
   ║  frontend's canonical shape. It performs NO computation, ║
   ║  estimation, or inference of Trust Engine outputs.       ║
   ║                                                          ║
   ║  The ONLY derived value: temp_avg (arithmetic from two   ║
   ║  raw sensors). All Trust Engine fields are passed        ║
   ║  through as-is or set to null. Never inferred.           ║
   ╚══════════════════════════════════════════════════════════╝ */
function mapBackendPayload(raw) {
  if (!raw || typeof raw !== 'object') return null;

  const g = (key) => (raw[key] !== undefined && raw[key] !== null ? raw[key] : null);

  const temp1 = g('temp_1');
  const temp2 = g('temp_2');
  // temp_avg: the ONLY arithmetic derived value (two sensor readings averaged).
  // This is NOT a health inference — it is the sensor's composite reading.
  const tempAvg = (temp1 !== null && temp2 !== null)
    ? parseFloat(((temp1 + temp2) / 2).toFixed(2))
    : null;

  return {
    device_id: g('device_id'),
    timestamp:  g('recorded_at') ?? g('timestamp') ?? new Date().toISOString(),

    telemetry: {
      temp_1:    temp1,
      temp_2:    temp2,
      temp_avg:  tempAvg,
      rpm:       g('rpm'),
      vibration: g('vibration'),
      voltage:   g('voltage'),
      current:   g('current'),
      power:     g('power'),
      fan_on:    g('fan'),
      hall_raw:  g('hall_raw') ?? null,
    },

    // Trust Engine fields — PASS-THROUGH ONLY.
    // Set to null when backend does not provide them.
    // DO NOT compute these from raw telemetry.
    trust_score:      g('trust_score'),
    state:            g('state'),
    decision:         g('decision'),
    anomaly_summary:  g('anomaly_summary'),
    rule_summary:     g('rule_summary'),
    temporal_summary: g('temporal_summary'),
    score_breakdown:  g('score_breakdown'),
    reasons:          g('reasons'),
  };
}

/* Map the actual PulseTrust_ Trust Engine response into the frontend contract. */
function mapTrustPayload(raw, telemetry = null) {
  if (!raw || typeof raw !== 'object') return null;

  const s1 = raw.sensor_1 ?? {};
  const s2 = raw.sensor_2 ?? {};
  const t1 = s1.value ?? telemetry?.temp_1 ?? null;
  const t2 = s2.value ?? telemetry?.temp_2 ?? null;
  const tempAvg = (t1 !== null && t2 !== null)
    ? parseFloat(((Number(t1) + Number(t2)) / 2).toFixed(2))
    : null;

  const state = raw.state ?? null;
  const decision =
    state === 'TRUSTED' ? 'ALLOW' :
    state === 'DEGRADED' ? 'CAUTION' :
    state === 'UNTRUSTED' ? 'BLOCK' : null;

  const anomalyScores = [s1.anomaly_score, s2.anomaly_score]
    .filter(v => v !== null && v !== undefined && !Number.isNaN(Number(v)))
    .map(Number);

  return {
    device_id: raw.device_id ?? telemetry?.device_id ?? 'PulseTrust_ Simulation',
    timestamp: telemetry?.recorded_at ?? new Date().toISOString(),

    telemetry: {
      temp_1: t1,
      temp_2: t2,
      temp_avg: tempAvg,
      rpm: telemetry?.rpm ?? null,
      vibration: telemetry?.vibration ?? null,
      voltage: telemetry?.voltage ?? null,
      current: telemetry?.current ?? null,
      power: telemetry?.power ?? null,
      fan_on: telemetry?.fan ?? null,
      hall_raw: telemetry?.hall_raw ?? null,
    },

    trust_score: raw.trust_score ?? null,
    state,
    decision,

    anomaly_summary: {
      is_anomaly: Boolean(s1.anomaly) || Boolean(s2.anomaly),
      anomaly_score: anomalyScores.length ? Math.min(...anomalyScores) : null,
      normalized_score: null,
      model_status: 'Isolation Forest Active',
      features_used: 6,
    },

    rule_summary: {
      violations: raw.reasons ?? [],
      warning_count: state === 'DEGRADED' ? (raw.reasons?.length ?? 0) : 0,
      critical_count: state === 'UNTRUSTED' ? (raw.reasons?.length ?? 0) : 0,
    },

    temporal_summary: null,
    score_breakdown: null,
    reasons: raw.reasons ?? [],
    agreement: raw.agreement ?? null,
    corroborated_event: raw.corroborated_event ?? false,
  };
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  3. DEMO HISTORY GENERATOR                               ║
   ║     (must be defined before DEMO_SCENARIOS uses it)      ║
   ╚══════════════════════════════════════════════════════════╝ */
function generateDemoHistory(scenario) {
  const history = [];
  const now = Date.now();
  const interval = 5000; // 5 s per reading

  const profiles = {
    HEALTHY: {
      trust:     ()  => 96 + Math.random() * 4,
      state:     ()  => 'NORMAL',
      decision:  ()  => 'ALLOW',
      temp:      ()  => 41 + Math.random() * 3,
      rpm:       ()  => 1460 + Math.random() * 40,
      current:   ()  => 1.65 + Math.random() * 0.08,
      power:     ()  => 19.5 + Math.random() * 1.5,
      vibration: ()  => 0.88 + Math.random() * 0.12,
      voltage:   ()  => 11.90 + Math.random() * 0.08,
    },
    ANOMALY: {
      trust:     (i) => Math.max(60, 85 - i * 0.8 + (Math.random() - 0.5) * 5),
      state:     (i) => i < 10 ? 'NORMAL' : 'CAUTION',
      decision:  (i) => i < 10 ? 'ALLOW' : 'WARN',
      temp:      (i) => 42 + i * 0.5 + Math.random() * 2,
      rpm:       (i) => 1480 - i * 3 + Math.random() * 15,
      current:   (i) => 1.68 + i * 0.012 + Math.random() * 0.04,
      power:     (i) => 20.0 + i * 0.15 + Math.random() * 0.4,
      vibration: (i) => 0.92 + i * 0.02 + Math.random() * 0.04,
      voltage:   ()  => 11.72 + Math.random() * 0.08,
    },
    DEGRADING: {
      trust:     (i) => Math.max(48, 80 - i * 1.2 + (Math.random() - 0.5) * 4),
      state:     (i) => i < 8 ? 'NORMAL' : i < 18 ? 'CAUTION' : 'DEGRADING',
      decision:  (i) => i < 8 ? 'ALLOW' : 'WARN',
      temp:      (i) => 43 + i * 0.78 + Math.random() * 2,
      rpm:       (i) => 1490 - i * 14 + Math.random() * 12,
      current:   (i) => 1.68 + i * 0.025 + Math.random() * 0.04,
      power:     (i) => 20.0 + i * 0.35 + Math.random() * 0.4,
      vibration: (i) => 0.92 + i * 0.04 + Math.random() * 0.04,
      voltage:   ()  => 11.55 + Math.random() * 0.08,
    },
    FAULT: {
      trust:     (i) => Math.max(15, 90 - i * 2.8 + (Math.random() - 0.5) * 5),
      state:     (i) => i < 6 ? 'NORMAL' : i < 14 ? 'CAUTION' : i < 22 ? 'DEGRADING' : 'FAULT',
      decision:  (i) => i < 6 ? 'ALLOW' : i < 22 ? 'WARN' : 'BLOCK',
      temp:      (i) => 42 + i * 1.7 + Math.random() * 3,
      rpm:       (i) => Math.max(0, 1490 - i * 75 + Math.random() * 15),
      current:   (i) => i < 22 ? 1.68 + i * 0.04 : 0.08 + Math.random() * 0.04,
      power:     (i) => i < 22 ? 20.0 + i * 0.5  : 0.90 + Math.random() * 0.15,
      vibration: (i) => i < 22 ? 0.92 + i * 0.04 : 0.22 + Math.random() * 0.04,
      voltage:   ()  => 11.22 + Math.random() * 0.08,
    },
  };

  const p = profiles[scenario];
  for (let i = 0; i < 30; i++) {
    const t1  = parseFloat((p.temp(i) - 0.7 + Math.random() * 0.4).toFixed(2));
    const t2  = parseFloat((p.temp(i) + 0.7 + Math.random() * 0.4).toFixed(2));
    const rpm = parseFloat(p.rpm(i).toFixed(0));
    const cur = parseFloat(p.current(i).toFixed(3));
    const pwr = parseFloat(p.power(i).toFixed(2));
    const vib = parseFloat(p.vibration(i).toFixed(3));
    const vlt = parseFloat(p.voltage().toFixed(2));
    const ts  = parseFloat(p.trust(i).toFixed(1));
    const st  = p.state(i);
    const dec = p.decision(i);

    history.push({
      timestamp: new Date(now - (29 - i) * interval).toISOString(),
      telemetry: {
        temp_1: t1, temp_2: t2, temp_avg: parseFloat(((t1+t2)/2).toFixed(2)),
        rpm, current: cur, power: pwr, vibration: vib, voltage: vlt,
        fan_on: rpm > 50, hall_raw: Math.round(rpm * 0.998),
      },
      trust_score: ts,
      state: st,
      decision: dec,
      reasons: [],
    });
  }
  return history;
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  3b. DEMO MODE SCENARIOS                                 ║
   ║      Pre-authored complete contract objects.             ║
   ║      No computation — backend contract reproduced        ║
   ║      verbatim as representative sample data.             ║
   ╚══════════════════════════════════════════════════════════╝ */
const DEMO_SCENARIOS = {
  HEALTHY: {
    device_id: 'trusttwin-plant-01',
    timestamp: new Date().toISOString(),
    telemetry: {
      temp_1: 41.8, temp_2: 43.2, temp_avg: 42.5,
      rpm: 1480, vibration: 0.92, voltage: 11.94,
      current: 1.68, power: 20.05, fan_on: true, hall_raw: 1478,
    },
    trust_score: 98.5,
    state: 'NORMAL',
    decision: 'ALLOW',
    anomaly_summary: {
      is_anomaly: false,
      anomaly_score: 0.042,
      normalized_score: 0.71,
      model_status: 'ready',
      features_used: 34,
    },
    rule_summary: {
      violations: [],
      warning_count: 0,
      critical_count: 0,
    },
    temporal_summary: {
      temp_rate: 0.012, rpm_rate: 2.1, current_rate: 0.001,
      vibration_rate: 0.005,
      persistence: { temp: 0, rpm: 0, current: 0, vibration: 0 },
    },
    score_breakdown: {
      base: 100, anomaly_penalty: 0, warning_penalty: 0,
      critical_penalty: 0, degradation_penalty: 1.5,
    },
    reasons: [],
    history: generateDemoHistory('HEALTHY'),
  },

  ANOMALY: {
    device_id: 'trusttwin-plant-01',
    timestamp: new Date().toISOString(),
    telemetry: {
      temp_1: 52.1, temp_2: 54.8, temp_avg: 53.45,
      rpm: 1390, vibration: 1.41, voltage: 11.72,
      current: 1.95, power: 22.87, fan_on: true, hall_raw: 1388,
    },
    trust_score: 67.0,
    state: 'CAUTION',
    decision: 'WARN',
    anomaly_summary: {
      is_anomaly: true,
      anomaly_score: -0.148,
      normalized_score: 0.31,
      model_status: 'ready',
      features_used: 34,
    },
    rule_summary: {
      violations: [
        {
          rule: 'HIGH_TEMPERATURE', severity: 'WARNING',
          metric: 'temp_avg', value: 53.45, threshold: 50.0,
        },
      ],
      warning_count: 1,
      critical_count: 0,
    },
    temporal_summary: {
      temp_rate: 0.182, rpm_rate: -11.8, current_rate: 0.033,
      vibration_rate: 0.061,
      persistence: { temp: 2, rpm: 1, current: 2, vibration: 1 },
    },
    score_breakdown: {
      base: 100, anomaly_penalty: 18, warning_penalty: 10,
      critical_penalty: 0, degradation_penalty: 5,
    },
    reasons: [
      'Isolation Forest detected unusual operating pattern',
      'Temperature above warning threshold (53.5 °C / limit 50.0 °C)',
      'Current consumption elevated above baseline',
    ],
    history: generateDemoHistory('ANOMALY'),
  },

  DEGRADING: {
    device_id: 'trusttwin-plant-01',
    timestamp: new Date().toISOString(),
    telemetry: {
      temp_1: 61.3, temp_2: 64.2, temp_avg: 62.75,
      rpm: 1210, vibration: 1.78, voltage: 11.51,
      current: 2.31, power: 26.59, fan_on: true, hall_raw: 1207,
    },
    trust_score: 52.0,
    state: 'DEGRADING',
    decision: 'WARN',
    anomaly_summary: {
      is_anomaly: true,
      anomaly_score: -0.241,
      normalized_score: 0.18,
      model_status: 'ready',
      features_used: 34,
    },
    rule_summary: {
      violations: [
        {
          rule: 'HIGH_TEMPERATURE', severity: 'WARNING',
          metric: 'temp_avg', value: 62.75, threshold: 50.0,
        },
        {
          rule: 'HIGH_CURRENT', severity: 'WARNING',
          metric: 'current', value: 2.31, threshold: 2.0,
        },
      ],
      warning_count: 2,
      critical_count: 0,
    },
    temporal_summary: {
      temp_rate: 0.341, rpm_rate: -28.5, current_rate: 0.071,
      vibration_rate: 0.119,
      persistence: { temp: 3, rpm: 3, current: 3, vibration: 2 },
    },
    score_breakdown: {
      base: 100, anomaly_penalty: 24, warning_penalty: 14,
      critical_penalty: 0, degradation_penalty: 10,
    },
    reasons: [
      'RPM falling for 3 consecutive readings',
      'Current consumption increasing for 3 consecutive readings',
      'Temperature rising persistently above warning threshold',
      'Isolation Forest detected significant deviation from normal pattern',
    ],
    history: generateDemoHistory('DEGRADING'),
  },

  FAULT: {
    device_id: 'trusttwin-plant-01',
    timestamp: new Date().toISOString(),
    telemetry: {
      temp_1: 78.4, temp_2: 81.9, temp_avg: 80.15,
      rpm: 0, vibration: 0.22, voltage: 11.21,
      current: 0.08, power: 0.90, fan_on: false, hall_raw: 0,
    },
    trust_score: 18.0,
    state: 'FAULT',
    decision: 'BLOCK',
    anomaly_summary: {
      is_anomaly: true,
      anomaly_score: -0.512,
      normalized_score: 0.02,
      model_status: 'ready',
      features_used: 34,
    },
    rule_summary: {
      violations: [
        {
          rule: 'FAN_STOPPED', severity: 'CRITICAL',
          metric: 'fan_on', value: false, threshold: true,
        },
        {
          rule: 'CRITICAL_TEMPERATURE', severity: 'CRITICAL',
          metric: 'temp_avg', value: 80.15, threshold: 75.0,
        },
        {
          rule: 'RPM_STALL', severity: 'CRITICAL',
          metric: 'rpm', value: 0, threshold: 100,
        },
      ],
      warning_count: 0,
      critical_count: 3,
    },
    temporal_summary: {
      temp_rate: 0.891, rpm_rate: -210.0, current_rate: -0.181,
      vibration_rate: -0.218,
      persistence: { temp: 3, rpm: 3, current: 3, vibration: 3 },
    },
    score_breakdown: {
      base: 100, anomaly_penalty: 51, warning_penalty: 0,
      critical_penalty: 25, degradation_penalty: 6,
    },
    reasons: [
      'Fan stopped — critical rule violated',
      'Temperature critical (80.2 °C / limit 75.0 °C)',
      'RPM stall detected — motor not rotating',
      'Isolation Forest: extreme deviation from healthy pattern',
    ],
    history: generateDemoHistory('FAULT'),
  },
};

/* ╔══════════════════════════════════════════════════════════╗
   ║  4. APPLICATION STATE                                    ║
   ╚══════════════════════════════════════════════════════════╝ */
const appState = {
  mode:            'live',     // 'live' | 'demo'
  data:            null,       // current canonical payload (null = loading)
  history:         [],         // array of canonical payloads (oldest first)
  connected:       false,
  lastUpdated:     null,       // Date object
  activeScenario:  'normal',
  pollTimer:       null,
  lastRawPayload:  null,
  chartRanges: {               // seconds for each chart
    temperature: 300,
    rotation:    300,
    electrical:  300,
    modal:       300,
  },
};

/* ╔══════════════════════════════════════════════════════════╗
   ║  6. SCROLL REVEAL                                        ║
   ╚══════════════════════════════════════════════════════════╝ */
function initScrollReveal() {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (!reduceMotion) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          setTimeout(() => entry.target.classList.add('reveal--visible'), i * 70);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });

    document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
  } else {
    document.querySelectorAll('.reveal').forEach(el => el.classList.add('reveal--visible'));
  }
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  7. RENDER — HEADER                                      ║
   ╚══════════════════════════════════════════════════════════╝ */
function renderHeader() {
  const dot       = document.getElementById('status-dot');
  const deviceEl  = document.getElementById('status-device');
  const updatedEl = document.getElementById('status-updated');
  const demoPill  = document.getElementById('demo-pill');
  const { mode, data, connected, lastUpdated } = appState;

  // Connection dot
  dot.className = 'status-dot';
  if (mode === 'demo') {
    dot.className = 'status-dot status-dot--offline';
  } else if (connected) {
    dot.className = 'status-dot status-dot--connected';
  } else {
    dot.className = 'status-dot status-dot--offline';
  }

  deviceEl.textContent = data?.device_id ?? '—';

  if (lastUpdated) {
    const s = Math.round((Date.now() - lastUpdated.getTime()) / 1000);
    updatedEl.textContent = s < 5 ? 'just now' : `${s}s ago`;
  } else {
    updatedEl.textContent = '—';
  }

  demoPill.hidden = (mode !== 'demo');

  // Mirror device_id to technical details
  const techDev = document.getElementById('tech-device-id');
  if (techDev) techDev.textContent = data?.device_id ?? '—';
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  8. RENDER — HERO (Trust Score)                          ║
   ╚══════════════════════════════════════════════════════════╝ */
function renderHero() {
  const data = appState.data;
  const avail   = document.getElementById('hero-available');
  const unavail = document.getElementById('hero-unavailable');

  const trustScore = data?.trust_score ?? null;
  const state      = data?.state      ?? null;
  const decision   = data?.decision   ?? null;

  if (trustScore !== null) {
    avail.hidden   = false;
    unavail.hidden = true;

    // Score number
    document.getElementById('trust-score-number').textContent = trustScore.toFixed(1);

    // Radial progress ring (circumference 2π × 68 ≈ 427.26)
    const circ   = 427.26;
    const pct    = Math.min(Math.max(trustScore, 0), 100) / 100;
    const offset = circ - pct * circ;
    const ring   = document.getElementById('trust-ring-progress');
    ring.style.strokeDashoffset = offset.toFixed(2);
    ring.style.stroke           = stateToRingColor(state);

    // State dot + label
    const cls = stateToClass(state);
    const dot = document.getElementById('state-dot');
    dot.style.background = stateToColor(state);

    const lbl = document.getElementById('state-label');
    lbl.textContent  = state ?? '—';
    lbl.style.color  = stateToColor(state);

    // Decision badge
    const badge = document.getElementById('decision-badge');
    badge.textContent       = decision ?? '—';
    badge.style.background  = stateToColor(state);
  } else {
    avail.hidden   = true;
    unavail.hidden = false;
  }
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  9. RENDER — DIGITAL TWIN                                ║
   ╚══════════════════════════════════════════════════════════╝ */
function buildFanSVG() {
  // Monoline fan: hub + 6 curved blades. Center 120,120, viewBox 240×240.
  const cx = 120, cy = 120, hubR = 14;
  const blades = [];
  for (let b = 0; b < 6; b++) {
    const a0 = (b * 60 - 90) * (Math.PI / 180);
    const a1 = a0 + 0.38;
    const a2 = a0 + 0.68;
    const a3 = a0 + 0.98;
    const r0 = hubR + 3, r1 = 48, r2 = 72, r3 = 84;
    blades.push(`<path class="fan-blade"
      d="M ${(cx + Math.cos(a0)*r0).toFixed(2)} ${(cy + Math.sin(a0)*r0).toFixed(2)}
         C ${(cx + Math.cos(a1)*r1).toFixed(2)} ${(cy + Math.sin(a1)*r1).toFixed(2)},
           ${(cx + Math.cos(a2)*r2).toFixed(2)} ${(cy + Math.sin(a2)*r2).toFixed(2)},
           ${(cx + Math.cos(a3)*r3).toFixed(2)} ${(cy + Math.sin(a3)*r3).toFixed(2)}"
      fill="none" stroke-width="2.5" stroke-linecap="round" />`);
  }

  return `<svg id="fan-svg" viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true" focusable="false">
    <g id="fan-group" class="fan-group fan-rotating">
      ${blades.join('\n      ')}
      <circle id="fan-hub"        cx="${cx}" cy="${cy}" r="${hubR}" fill="none" stroke-width="2.5" />
      <circle id="fan-hub-center" cx="${cx}" cy="${cy}" r="4" />
    </g>
    <g id="fan-warn-glyph" opacity="0" aria-hidden="true" fill="none" stroke="var(--state-caution)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M182 46 L196 72 H168 Z"/><path d="M182 56 V64"/><path d="M182 68 V68.5"/></g>
  </svg>`;
}

function initDigitalTwin() {
  const canvas = document.getElementById('twin-canvas');
  if (canvas) canvas.innerHTML = buildFanSVG();

  // If reduced motion is preferred, strip the rotating class before the first paint
  // so the fan never starts spinning even momentarily.
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.getElementById('fan-group')?.classList.remove('fan-rotating');
  }

  setFanStroke('var(--color-graphite)');
}

function setFanStroke(color) {
  document.querySelectorAll('.fan-blade').forEach(b => b.setAttribute('stroke', color));
  const hub = document.getElementById('fan-hub');
  const hub2 = document.getElementById('fan-hub-center');
  if (hub)  hub.setAttribute('stroke', color);
  if (hub2) hub2.setAttribute('fill',  color);
}

function renderDigitalTwin() {
  const data   = appState.data;
  const rpm    = data?.telemetry?.rpm   ?? 0;
  const fanOn  = data?.telemetry?.fan_on ?? false;
  // state is only used if explicitly present; never inferred from raw telemetry
  const state  = data?.state ?? null;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const fanGroup  = document.getElementById('fan-group');
  const fanWarn   = document.getElementById('fan-warn-glyph');
  const rpmEl     = document.getElementById('twin-rpm-value');
  const badgeEl   = document.getElementById('twin-fan-badge');
  const deviceEl  = document.getElementById('twin-device-id');

  if (!fanGroup) return;

  // RPM display (always from raw telemetry)
  rpmEl.textContent = (rpm !== null && !isNaN(rpm)) ? String(Math.round(rpm)) : '—';

  // Fan badge
  if (data?.telemetry) {
    badgeEl.textContent = fanOn ? 'Fan ON' : 'Fan OFF';
    badgeEl.style.color      = fanOn ? 'var(--state-trusted)' : 'var(--color-slate)';
    badgeEl.style.background = fanOn ? 'rgba(61,107,79,0.08)' : 'var(--color-mist)';
  }

  deviceEl.textContent = data?.device_id ?? '—';

  // Rotation speed — always based on actual RPM (no Trust Engine dependency)
  if (!reduceMotion) {
    if (fanOn && rpm > 0) {
      const dur = Math.min(Math.max(60000 / rpm, 250), 4000);
      fanGroup.style.animationDuration = `${dur.toFixed(0)}ms`;
      fanGroup.classList.add('fan-rotating');
    } else {
      fanGroup.classList.remove('fan-rotating');
    }
  }

  // Stroke color — ONLY changes if state is explicitly in the payload.
  // If state === null (Trust Engine not available), stays neutral Graphite.
  let stroke = 'var(--color-graphite)';
  let warnOpacity = '0';

  if (state === 'DEGRADED' || state === 'CAUTION' || state === 'DEGRADING') {
    stroke = 'var(--state-caution)';
    warnOpacity = '1';
  } else if (state === 'UNTRUSTED' || state === 'FAULT') {
    stroke = 'var(--state-critical)';
    fanGroup.classList.remove('fan-rotating');
  } else if (state === 'OFFLINE') {
    stroke = 'var(--state-offline)';
    fanGroup.classList.remove('fan-rotating');
  }
  // state === null: no branch — stroke stays 'var(--color-graphite)'

  setFanStroke(stroke);
  if (fanWarn) fanWarn.setAttribute('opacity', warnOpacity);
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  10. RENDER — TELEMETRY CARDS                            ║
   ╚══════════════════════════════════════════════════════════╝ */
function renderTelemetry() {
  const t = appState.data?.telemetry;
  if (!t) return;

  const fmt  = (v, d = 1) => (v !== null && v !== undefined && !isNaN(v)) ? Number(v).toFixed(d) : '—';
  const fmtI = (v) => (v !== null && v !== undefined && !isNaN(v)) ? String(Math.round(v)) : '—';

  setTxt('tel-temp-avg', fmt(t.temp_avg));
  setTxt('tel-temp-1',   fmt(t.temp_1));
  setTxt('tel-temp-2',   fmt(t.temp_2));

  setTxt('tel-rpm',      fmtI(t.rpm));
  setTxt('tel-hall-raw', t.hall_raw !== null ? fmtI(t.hall_raw) : '—');

  setTxt('tel-power',   fmt(t.power, 2));
  setTxt('tel-voltage', fmt(t.voltage, 2));
  setTxt('tel-current', fmt(t.current, 3));
  setTxt('tel-fan',     t.fan_on !== null ? (t.fan_on ? 'ON' : 'OFF') : '—');

  setTxt('tel-vibration', fmt(t.vibration, 3));

  const vibTag = document.getElementById('tel-vibration-tag');
  if (vibTag && t.vibration !== null) {
    const elevated = t.vibration > 1.2;
    vibTag.textContent = elevated ? 'Elevated' : 'Normal';
    vibTag.className   = `vibration-tag ${elevated ? 'vibration-tag--elevated' : ''}`;
  }
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  11. RENDER — EVIDENCE PANELS                            ║
   ╚══════════════════════════════════════════════════════════╝ */
function renderEvidence() {
  renderIsolationForest();
  renderRuleEngine();
  renderTemporal();
}

function renderIsolationForest() {
  const body   = document.getElementById('evidence-isolation-body');
  const anomaly = appState.data?.anomaly_summary ?? null;

  if (!anomaly) {
    body.innerHTML = '<p class="evidence-unavail">Awaiting Trust Engine data</p>';
    return;
  }

  const isAnomaly  = anomaly.is_anomaly;
  const score      = anomaly.anomaly_score      !== null ? anomaly.anomaly_score.toFixed(4) : '—';
  const normScore  = anomaly.normalized_score   !== null ? (anomaly.normalized_score * 100).toFixed(1) + '%' : '—';

  body.innerHTML = `
    <div class="if-status ${isAnomaly ? 'if-status--anomaly' : 'if-status--normal'}">
      ${icon(isAnomaly ? 'warn' : 'check')}${isAnomaly ? 'Anomaly detected' : 'Normal'}
    </div>
    <div class="if-metric-list">
      <div class="if-metric-row">
        <span class="if-metric-label">Anomaly score</span>
        <span class="if-metric-value">${esc(score)}</span>
      </div>
      <div class="if-metric-row">
        <span class="if-metric-label">Normalized score</span>
        <span class="if-metric-value">${esc(normScore)}</span>
      </div>
      <div class="if-metric-row">
        <span class="if-metric-label">Model status</span>
        <span class="if-metric-value">${esc(anomaly.model_status ?? '—')}</span>
      </div>
      <div class="if-metric-row">
        <span class="if-metric-label">Features used</span>
        <span class="if-metric-value">${esc(String(anomaly.features_used ?? '—'))}</span>
      </div>
    </div>`;
}

function renderRuleEngine() {
  const body   = document.getElementById('evidence-rule-body');
  const ruleSummary = appState.data?.rule_summary ?? null;

  if (!ruleSummary) {
    body.innerHTML = '<p class="evidence-unavail">Awaiting Trust Engine data</p>';
    return;
  }

  // Backend may send violations as plain strings; normalise to one shape.
  const violations = (ruleSummary.violations ?? []).map(v =>
    typeof v === 'string' ? { rule: v, text: v } : v);

  // Map each check category to whether it's violated
  const checks = [
    { key: 'Temperature',     ruleHint: ['TEMP', 'temp'] },
    { key: 'Current',         ruleHint: ['CURRENT', 'current'] },
    { key: 'RPM',             ruleHint: ['RPM', 'rpm'] },
    { key: 'Fan behaviour',   ruleHint: ['FAN', 'fan'] },
    { key: 'Sensor agreement',ruleHint: ['SENSOR', 'AGREEMENT', 'sensor'] },
  ];

  const rows = checks.map(chk => {
    const violation = violations.find(v =>
      chk.ruleHint.some(h =>
        (v.rule   ?? '').toLowerCase().includes(h.toLowerCase()) ||
        (v.metric ?? '').toLowerCase().includes(h.toLowerCase())
      )
    );
    const pass = !violation;
    let html = `<div class="rule-item">
      <div class="rule-item-header">
        ${icon(pass ? 'check' : 'cross', pass ? 'rule-icon--pass' : 'rule-icon--fail')}
        <span class="rule-label ${pass ? '' : 'rule-label--fail'}">${esc(chk.key)}</span>
      </div>`;
    if (violation) {
      const detail = violation.text ? esc(violation.text) : `${esc(violation.rule)} — ${esc(violation.severity)} — ${esc(String(violation.metric))}: ${esc(String(violation.value))} / threshold: ${esc(String(violation.threshold))}`;
      html += `<div class="rule-violation-detail">${detail}</div>`;
    }
    html += `</div>`;
    return html;
  }).join('');

  const total = violations.length;
  const summaryText = total === 0
    ? '0 violations — all rules satisfied'
    : `${ruleSummary.warning_count ?? 0} warning · ${ruleSummary.critical_count ?? 0} critical`;

  body.innerHTML = `<div class="rule-list">${rows}</div>
    <p class="rule-summary-text">${summaryText}</p>`;
}

function renderTemporal() {
  const body    = document.getElementById('evidence-temporal-body');
  const temporal = appState.data?.temporal_summary ?? null;

  if (!temporal) {
    body.innerHTML = '<p class="evidence-unavail">Awaiting Trust Engine data</p>';
    return;
  }

  const pers = temporal.persistence ?? {};

  const metrics = [
    { label: 'Temperature', rate: temporal.temp_rate,      count: pers.temp      ?? 0, unit: '°C/s' },
    { label: 'RPM',         rate: temporal.rpm_rate,       count: pers.rpm       ?? 0, unit: '/s'   },
    { label: 'Current',     rate: temporal.current_rate,   count: pers.current   ?? 0, unit: 'A/s'  },
    { label: 'Vibration',   rate: temporal.vibration_rate, count: pers.vibration ?? 0, unit: 'g/s'  },
  ];

  const rows = metrics.map(m => {
    const rateStr = (m.rate !== null && m.rate !== undefined)
      ? (m.rate >= 0 ? '+' : '') + m.rate.toFixed(4) + ' ' + m.unit
      : '—';

    // 3/3 = persistent → caution styling
    // 1/3 or 2/3 = informational only (neutral pill, no caution color)
    const isPersistent = m.count >= 3;
    const pillClass    = isPersistent ? 'temporal-pill--persistent' : '';
    const pillText     = m.count > 0
      ? `${m.count} of 3${isPersistent ? ', persistent' : ''}`
      : null;

    return `<div class="temporal-row">
      <span class="temporal-label">${esc(m.label)}</span>
      <span class="temporal-rate">${esc(rateStr)}</span>
      ${pillText ? `<span class="temporal-pill ${pillClass}">${pillText}</span>` : ''}
    </div>`;
  }).join('');

  body.innerHTML = `<div class="temporal-list">${rows}</div>`;
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  12. RENDER — SCORE BREAKDOWN                            ║
   ║      Renders score_breakdown as-is from backend.         ║
   ║      Zero computation in this function.                  ║
   ╚══════════════════════════════════════════════════════════╝ */
function renderBreakdown() {
  const data      = appState.data;
  const ledger    = document.getElementById('breakdown-ledger');
  const unavail   = document.getElementById('breakdown-unavailable');
  const breakdown = data?.score_breakdown ?? null;

  if (!breakdown) {
    ledger.hidden  = true;
    unavail.hidden = false;
    return;
  }

  ledger.hidden  = false;
  unavail.hidden = true;

  // Render each field directly from the backend object — NO recomputation
  setTxt('bd-base',        `+${breakdown.base ?? 100}`);
  setTxt('bd-anomaly',     fmtPenalty(breakdown.anomaly_penalty));
  setTxt('bd-warning',     fmtPenalty(breakdown.warning_penalty));
  setTxt('bd-critical',    fmtPenalty(breakdown.critical_penalty));
  setTxt('bd-degradation', fmtPenalty(breakdown.degradation_penalty));

  // Final total: read from data.trust_score (also backend-provided)
  setTxt('bd-total', data?.trust_score !== null ? data.trust_score.toFixed(1) : '—');
}

function fmtPenalty(v) {
  if (v === null || v === undefined) return '0';
  const n = Number(v);
  if (n === 0) return '0';
  return `−${n.toFixed(1)}`; // en-dash minus for display
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  13. RENDER — DECISION EXPLANATION                       ║
   ║      Rendered exclusively from backend reasons/evidence. ║
   ║      No invented copy.                                   ║
   ╚══════════════════════════════════════════════════════════╝ */
function renderDecision() {
  const data     = appState.data;
  const unavail  = document.getElementById('decision-unavailable');
  const content  = document.getElementById('decision-content');
  const reasons  = data?.reasons ?? null;
  const state    = data?.state   ?? null;
  const decision = data?.decision ?? null;

  // Always clear any stale inline style left by a previous render
  unavail.style.display = '';

  if (reasons === null) {
    unavail.hidden = false;
    content.hidden = true;
    return;
  }

  // Trust Engine data is present — show content, hide placeholder
  unavail.hidden = true;
  content.hidden = false;

  const statusMap = {
    TRUSTED:   { icon: 'check',  label: 'Sensors trusted',     color: 'var(--state-trusted)'  },
    NORMAL:    { icon: 'check',  label: 'Sensors trusted',     color: 'var(--state-trusted)'  },
    CAUTION:   { icon: 'warn', label: 'Machine in caution', color: 'var(--state-caution)'  },
    DEGRADED:  { icon: 'warn', label: 'Sensor trust degraded', color: 'var(--state-caution)'  },
    DEGRADING: { icon: 'warn', label: 'Sensor trust degraded', color: 'var(--state-caution)'  },
    UNTRUSTED: { icon: 'block', label: 'Sensors untrusted',    color: 'var(--state-critical)' },
    FAULT:     { icon: 'block', label: 'Sensors untrusted',    color: 'var(--state-critical)' },
    OFFLINE:   { icon: 'block', label: 'Machine offline',    color: 'var(--state-critical)' },
  };
  const s = statusMap[state] ?? { icon: '', label: state ?? '—', color: 'var(--color-steel)' };

  const statusLineEl = document.getElementById('decision-status-line');
  statusLineEl.innerHTML = `${icon(s.icon)}<span>${esc(s.label)}</span>`;
  statusLineEl.style.color = s.color;

  const reasonsEl = document.getElementById('decision-reasons');
  if (reasons.length === 0 && (state === 'TRUSTED' || state === 'NORMAL')) {
    reasonsEl.innerHTML = `<li class="decision-reason-item">
      Current behaviour matches the learned healthy operating pattern.
      No critical rules violated. No persistent degradation detected.
    </li>`;
  } else {
    reasonsEl.innerHTML = reasons.map(r =>
      `<li class="decision-reason-item">${esc(r)}</li>`
    ).join('');
  }

  const verdictEl = document.getElementById('decision-verdict');
  verdictEl.textContent = `Decision: ${decision ?? '—'}`;
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  14. SHARED CHART RENDERER                               ║
   ║      Used by inline Live Charts section AND the modal.   ║
   ║      One function, reused everywhere — no drift.         ║
   ╚══════════════════════════════════════════════════════════╝ */
// series = [{ label: string, color: string, points: [{ t: number, value: number }] }]
function renderLineChart(container, series, { height = 220 } = {}) {
  if (!container) return;
  container.innerHTML = '';

  const allPts  = series.flatMap(s => s.points).filter(p => !isNaN(p.value));
  if (allPts.length === 0) {
    container.innerHTML = `<div style="height:${height}px;display:flex;align-items:center;
      justify-content:center;font-family:'Inter',sans-serif;font-size:14px;
      color:var(--color-slate)">No data in this range</div>`;
    return;
  }

  const W  = container.clientWidth || 560;
  const pad = { t: 16, r: 16, b: 24, l: 42 };
  const iW = W  - pad.l - pad.r;
  const iH = height - pad.t - pad.b;

  const allVals = allPts.map(p => p.value);
  const allTs   = allPts.map(p => p.t);
  const vMin = Math.min(...allVals), vMax = Math.max(...allVals);
  const tMin = Math.min(...allTs),   tMax = Math.max(...allTs);
  const vR   = vMax - vMin || 1;
  const tR   = tMax - tMin || 1;

  const px = t => pad.l + ((t - tMin) / tR) * iW;
  const py = v => pad.t + iH - ((v - vMin) / vR) * iH;

  // Y-axis grid + labels
  const yTicks = 3;
  let gridSvg = '';
  for (let i = 0; i < yTicks; i++) {
    const frac = i / (yTicks - 1);
    const v    = vMin + frac * vR;
    const y    = py(v);
    gridSvg += `<line x1="${pad.l}" y1="${y.toFixed(1)}"
                      x2="${(pad.l + iW).toFixed(1)}" y2="${y.toFixed(1)}"
                      stroke="var(--color-mist)" stroke-width="1" opacity="0.7" />
                <text x="${(pad.l - 5).toFixed(1)}" y="${y.toFixed(1)}"
                      text-anchor="end" dominant-baseline="middle"
                      font-family="Inter,sans-serif" font-size="10"
                      fill="var(--color-slate)">${v.toFixed(1)}</text>`;
  }

  // X-axis time labels
  let xSvg = '';
  const xTicks = [tMin, (tMin + tMax) / 2, tMax];
  xTicks.forEach(t => {
    const label = new Date(t).toLocaleTimeString([], { hour:'2-digit', minute:'2-digit', second:'2-digit' });
    xSvg += `<text x="${px(t).toFixed(1)}" y="${(pad.t + iH + 14).toFixed(1)}"
               text-anchor="middle" font-family="Inter,sans-serif" font-size="10"
               fill="var(--color-slate)">${label}</text>`;
  });

  // Series paths + gradient areas
  let seriesSvg = '';
  series.forEach(s => {
    const sorted = [...s.points].filter(p => !isNaN(p.value)).sort((a, b) => a.t - b.t);
    if (!sorted.length) return;

    const line  = sorted.map((p, i) => `${i === 0 ? 'M' : 'L'}${px(p.t).toFixed(1)},${py(p.value).toFixed(1)}`).join(' ');
    const first = sorted[0], last = sorted[sorted.length - 1];

    seriesSvg += `
      <path d="${line}" fill="none" stroke="${s.color}" stroke-width="2"
            stroke-linejoin="round" stroke-linecap="round"/>`;
  });

  const svgId = `cs${Math.random().toString(36).slice(2,7)}`;
  container.innerHTML = `
    <div style="position:relative">
      <svg id="${svgId}" viewBox="0 0 ${W} ${height}" width="100%" height="${height}"
           style="overflow:visible;display:block">
        ${gridSvg}${xSvg}${seriesSvg}
      </svg>
      <div class="chart-xhair" id="xh-${svgId}"></div>
      <div class="chart-tip"   id="ct-${svgId}"></div>
    </div>`;

  // Crosshair
  setupCrosshair(svgId, series, px, py, pad, W, height, tMin, tMax, vMin, vR);
}

function setupCrosshair(svgId, series, px, py, pad, W, height, tMin, tMax, vMin, vR) {
  const svg  = document.getElementById(svgId);
  const xhEl = document.getElementById(`xh-${svgId}`);
  const tipEl = document.getElementById(`ct-${svgId}`);
  if (!svg || !xhEl || !tipEl) return;

  const getX = e => e.touches ? e.touches[0].clientX : e.clientX;

  const onMove = (e) => {
    const rect = svg.getBoundingClientRect();
    const relX = getX(e) - rect.left;
    const scaleX = W / rect.width;
    const svgX   = relX * scaleX;
    const tAtX   = tMin + ((svgX - pad.l) / (W - pad.l - pad.r)) * (tMax - tMin);

    // Find nearest timestamp across all series
    const allPts = series.flatMap(s => s.points);
    if (!allPts.length) return;
    const nearest = allPts.reduce((best, p) =>
      Math.abs(p.t - tAtX) < Math.abs(best.t - tAtX) ? p : best
    );

    // Crosshair line
    const xScreen = (px(nearest.t) / W) * rect.width;
    xhEl.style.display = 'block';
    xhEl.style.left    = `${xScreen.toFixed(0)}px`;
    xhEl.style.top     = `${pad.t}px`;
    xhEl.style.height  = `${height - pad.t - pad.b}px`;

    // Tooltip
    const time = new Date(nearest.t).toLocaleTimeString([], { hour:'2-digit', minute:'2-digit', second:'2-digit' });
    const valLines = series.map(s => {
      const pt = s.points.reduce((b, p) => Math.abs(p.t - nearest.t) < Math.abs(b.t - nearest.t) ? p : b, s.points[0] ?? { t: 0, value: NaN });
      if (!pt || isNaN(pt.value)) return '';
      return `<div style="color:${s.color}">${esc(s.label)}: <b>${pt.value.toFixed(2)}</b></div>`;
    }).filter(Boolean).join('');

    tipEl.innerHTML   = `<div style="color:var(--color-slate);font-size:11px;margin-bottom:3px">${time}</div>${valLines}`;
    tipEl.style.display = 'block';

    // Position tooltip within container
    const cW = (tipEl.parentElement?.clientWidth ?? rect.width);
    let left = xScreen + 14;
    if (left + 160 > cW) left = xScreen - 170;
    tipEl.style.left = `${left.toFixed(0)}px`;
    tipEl.style.top  = `${(pad.t + 8).toFixed(0)}px`;
  };

  const onLeave = () => {
    xhEl.style.display  = 'none';
    tipEl.style.display = 'none';
  };

  svg.addEventListener('mousemove',  onMove);
  svg.addEventListener('mouseleave', onLeave);
  svg.addEventListener('touchmove',  onMove, { passive: true });
  svg.addEventListener('touchend',   onLeave);
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  15. CHARTS SECTION                                      ║
   ╚══════════════════════════════════════════════════════════╝ */
const CHARTS = {
  temperature: {
    containerId: 'chart-temperature',
    legendId:    'chart-legend-temperature',
    series: [
      { label: 'Avg',      color: 'var(--color-ember)', key: 'temp_avg' },
      { label: 'Sensor 1', color: 'var(--color-brass)', key: 'temp_1'   },
      { label: 'Sensor 2', color: 'var(--color-steel)', key: 'temp_2'   },
    ],
  },
  rotation: {
    containerId: 'chart-rotation',
    legendId:    'chart-legend-rotation',
    series: [
      { label: 'RPM', color: 'var(--color-ember)', key: 'rpm' },
    ],
  },
  electrical: {
    containerId: 'chart-electrical',
    legendId:    'chart-legend-electrical',
    series: [
      { label: 'Current (A)', color: 'var(--color-ember)', key: 'current' },
      { label: 'Power (W)',   color: 'var(--color-brass)', key: 'power'   },
    ],
  },
  vibration: {
    containerId: null, // modal only
    legendId:    null,
    series: [
      { label: 'Vibration (g)', color: 'var(--color-ember)', key: 'vibration' },
    ],
  },
};

function buildSeries(chartKey, rangeSeconds) {
  const def      = CHARTS[chartKey];
  const cutoff   = Date.now() - rangeSeconds * 1000;
  let filtered   = appState.history.filter(h => new Date(h.timestamp).getTime() >= cutoff);
  if (filtered.length < 2) filtered = appState.history.slice(-10);

  // Resolve active violations from the current backend payload — pass-through only.
  // Color override is driven by explicit rule_summary.violations, never inferred from raw telemetry.
  const violations = appState.data?.rule_summary?.violations ?? [];

  function violationColorFor(metricKey) {
    const hit = violations.find(v => (v.metric ?? '') === metricKey);
    if (!hit) return null;
    const sev = (hit.severity ?? '').toUpperCase();
    if (sev === 'CRITICAL') return 'var(--state-critical)';
    // WARNING / CAUTION → state-caution
    return 'var(--state-caution)';
  }

  return def.series.map(sd => {
    const override = violationColorFor(sd.key);
    return {
      label: sd.label,
      color: override ?? sd.color,   // backend violation takes precedence; default otherwise
      points: filtered
        .map(h => ({ t: new Date(h.timestamp).getTime(), value: h.telemetry?.[sd.key] }))
        .filter(p => p.value !== null && p.value !== undefined && !isNaN(p.value)),
    };
  });
}

function renderAllCharts() {
  ['temperature', 'rotation', 'electrical'].forEach(key => {
    const def = CHARTS[key];
    if (!def.containerId) return;
    const el = document.getElementById(def.containerId);
    if (!el) return;
    const series = buildSeries(key, appState.chartRanges[key]);
    renderLineChart(el, series);
    renderLegend(def.legendId, series);
  });
}

function renderLegend(legendId, series) {
  const el = document.getElementById(legendId);
  if (!el) return;
  el.innerHTML = series.map(s => `
    <div class="chart-legend-item">
      <div class="chart-legend-swatch" style="background:${s.color}"></div>
      <span>${esc(s.label)}</span>
    </div>`).join('');
}

function initRangeControls() {
  document.querySelectorAll('.range-controls:not(.modal-range-controls)').forEach(group => {
    const chartKey = group.dataset.chart;
    group.querySelectorAll('.range-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const range = parseInt(btn.dataset.range, 10);
        appState.chartRanges[chartKey] = range;
        // Update button styles
        group.querySelectorAll('.range-btn').forEach(b => {
          b.className = `range-btn ${b === btn ? 'btn--cta' : 'btn--ghost'}`;
          b.setAttribute('aria-pressed', String(b === btn));
        });
        // Re-render that specific chart
        if (CHARTS[chartKey]?.containerId) {
          const el = document.getElementById(CHARTS[chartKey].containerId);
          if (el) renderLineChart(el, buildSeries(chartKey, range));
        }
      });
    });
  });
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  16. TIMELINE                                            ║
   ╚══════════════════════════════════════════════════════════╝ */
function renderTimeline() {
  const track  = document.getElementById('timeline-track');
  const detail = document.getElementById('timeline-detail');
  if (!track) return;
  track.innerHTML = '';
  if (detail) detail.hidden = true;

  const history = appState.history;
  if (!history.length) {
    track.innerHTML = `<span style="font-family:'Inter',sans-serif;font-size:14px;color:var(--color-slate)">No history yet</span>`;
    return;
  }

  // Show up to 20 most recent
  const shown = history.slice(-20);
  shown.forEach((entry, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'timeline-dot-wrap';

    if (i > 0) {
      const conn = document.createElement('div');
      conn.className = 'timeline-connector';
      wrap.appendChild(conn);
    }

    const dot = document.createElement('button');
    dot.className   = 'timeline-dot';
    dot.setAttribute('role', 'listitem');
    dot.setAttribute('aria-label',
      `Reading ${i + 1}: ${entry.state ?? 'unknown'} at ${new Date(entry.timestamp).toLocaleTimeString()}`);

    // Color only if state is explicitly present
    if (entry.state) {
      dot.style.background = stateToColor(entry.state);
    }

    dot.addEventListener('click', () => {
      track.querySelectorAll('.timeline-dot--active').forEach(d => d.classList.remove('timeline-dot--active'));
      dot.classList.add('timeline-dot--active');
      showTimelineDetail(entry);
    });

    dot.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); dot.click(); }
    });

    wrap.appendChild(dot);
    track.appendChild(wrap);
  });
}

function showTimelineDetail(entry) {
  const el = document.getElementById('timeline-detail');
  if (!el) return;

  const fmt = (v, d = 1) => (v !== null && v !== undefined && !isNaN(v)) ? Number(v).toFixed(d) : '—';
  const t   = entry.telemetry ?? {};
  const time = new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const score   = entry.trust_score !== null && entry.trust_score !== undefined ? Number(entry.trust_score).toFixed(1) : '—';
  const state   = entry.state    ?? '—';
  const decision = entry.decision ?? '—';
  const stateColor = entry.state ? stateToColor(entry.state) : 'inherit';

  const reasons = Array.isArray(entry.reasons) && entry.reasons.length
    ? entry.reasons.join(' · ')
    : (entry.state === 'NORMAL' ? 'All rules satisfied. Normal operation.' : '');

  el.hidden = false;
  el.innerHTML = `
    <div class="timeline-detail-grid">
      <div class="timeline-detail-item">
        <span class="timeline-detail-label">Time</span>
        <span class="timeline-detail-value">${esc(time)}</span>
      </div>
      <div class="timeline-detail-item">
        <span class="timeline-detail-label">Trust score</span>
        <span class="timeline-detail-value">${esc(score)}</span>
      </div>
      <div class="timeline-detail-item">
        <span class="timeline-detail-label">State</span>
        <span class="timeline-detail-value" style="color:${stateColor}">${esc(state)}</span>
      </div>
      <div class="timeline-detail-item">
        <span class="timeline-detail-label">Decision</span>
        <span class="timeline-detail-value">${esc(decision)}</span>
      </div>
      ${reasons ? `<div class="timeline-detail-reasons">${esc(reasons)}</div>` : ''}
    </div>`;
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  17. TECHNICAL DETAILS                                   ║
   ╚══════════════════════════════════════════════════════════╝ */
function initTechnicalDetails() {
  const toggle = document.getElementById('technical-toggle');
  const panel  = document.getElementById('technical-panel');
  if (!toggle || !panel) return;

  toggle.addEventListener('click', () => {
    const open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open ? 'Hide technical details' : 'Show technical details';
  });
}

function renderTechnicalDetails() {
  const data   = appState.data;
  const anomaly = data?.anomaly_summary ?? null;
  setTxt('tech-model-status', anomaly?.model_status ?? '—');
  setTxt('tech-features',     String(anomaly?.features_used ?? 34));

  const rawLink = document.getElementById('technical-raw-link');
  if (rawLink && appState.lastRawPayload) {
    try {
      const blob = new Blob([JSON.stringify(appState.lastRawPayload, null, 2)], { type: 'application/json' });
      rawLink.href     = URL.createObjectURL(blob);
      rawLink.download = `payload-${Date.now()}.json`;
      rawLink.textContent = 'Download raw payload';
    } catch (_) {}
  }
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  18. MODAL                                               ║
   ╚══════════════════════════════════════════════════════════╝ */
const chartModal = (() => {
  let _category   = null;
  let _lastFocused = null;

  const titles = {
    temperature: 'Temperature',
    rotation:    'Rotation (RPM)',
    electrical:  'Current & Power',
    vibration:   'Vibration',
  };
  const subtitles = {
    temperature: 'Sensor 1 · Sensor 2 · Average',
    rotation:    'RPM',
    electrical:  'Current (A) · Power (W)',
    vibration:   'Vibration (g)',
  };

  function backdrop()  { return document.getElementById('modal-backdrop'); }
  function chartEl()   { return document.getElementById('modal-chart'); }
  function legendEl()  { return document.getElementById('modal-legend'); }
  function statsEl()   { return document.getElementById('modal-stats'); }
  function rangeGroup(){ return document.getElementById('modal-range-controls'); }

  function _renderChart() {
    const el = chartEl();
    if (!el || !_category) return;
    const range  = appState.chartRanges.modal;
    const series = buildSeries(_category, range);
    renderLineChart(el, series, { height: 280 });
    renderLegend('modal-legend', series);
    _renderStats(series);
  }

  function _renderStats(series) {
    const el = statsEl();
    if (!el) return;
    el.innerHTML = series.map(s => {
      if (!s.points.length) return '';
      const vals = s.points.map(p => p.value);
      const cur  = vals[vals.length - 1];
      const mn   = Math.min(...vals);
      const mx   = Math.max(...vals);
      const avg  = vals.reduce((a, b) => a + b, 0) / vals.length;
      return `<div>
        <div class="modal-stat-series-title" style="color:${s.color}">${esc(s.label)}</div>
        <div class="modal-stat-grid">
          <div class="modal-stat-item"><div class="modal-stat-label">Now</div><div class="modal-stat-value">${cur.toFixed(2)}</div></div>
          <div class="modal-stat-item"><div class="modal-stat-label">Avg</div><div class="modal-stat-value">${avg.toFixed(2)}</div></div>
          <div class="modal-stat-item"><div class="modal-stat-label">Min</div><div class="modal-stat-value">${mn.toFixed(2)}</div></div>
          <div class="modal-stat-item"><div class="modal-stat-label">Max</div><div class="modal-stat-value">${mx.toFixed(2)}</div></div>
        </div>
      </div>`;
    }).join('');
  }

  function open(category) {
    const bd = backdrop();
    if (!bd) return;
    _lastFocused = document.activeElement;
    _category = category;
    setTxt('modal-title',    titles[category]    ?? category);
    setTxt('modal-subtitle', subtitles[category] ?? '');
    _renderChart();
    bd.dataset.open = 'true';
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(() => document.getElementById('modal-close')?.focus());
  }

  function close() {
    const bd = backdrop();
    if (!bd) return;
    bd.dataset.open = 'false';
    document.body.style.overflow = '';
    _lastFocused?.focus();
    _category = null;
  }

  function init() {
    const bd = backdrop();
    if (!bd) return;

    document.getElementById('modal-close')?.addEventListener('click', close);
    bd.addEventListener('click', e => { if (e.target === bd) close(); });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && bd.dataset.open === 'true') close();
    });

    // Range controls
    const rg = rangeGroup();
    if (rg) {
      rg.querySelectorAll('.range-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const r = parseInt(btn.dataset.range, 10);
          appState.chartRanges.modal = r;
          rg.querySelectorAll('.range-btn').forEach(b => {
            b.className = `range-btn ${b === btn ? 'btn--cta' : 'btn--ghost'}`;
          });
          _renderChart();
        });
      });
    }

    // Focus trap
    const panel = bd.querySelector('.modal-panel');
    panel?.addEventListener('keydown', e => {
      if (e.key !== 'Tab') return;
      const els   = [...panel.querySelectorAll('button, a, [tabindex]:not([tabindex="-1"])')];
      const first = els[0], last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  function refresh() {
    if (backdrop()?.dataset.open === 'true') _renderChart();
  }

  return { init, open, close, refresh };
})();

/* ╔══════════════════════════════════════════════════════════╗
   ║  19. TELEMETRY CARD CLICKS                               ║
   ╚══════════════════════════════════════════════════════════╝ */
function initTelemetryCardClicks() {
  document.querySelectorAll('.telemetry-card').forEach(card => {
    const cat = card.dataset.category;
    card.addEventListener('click', () => chartModal.open(cat));
    card.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chartModal.open(cat); }
    });
  });
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  20. DATA POLLING                                        ║
   ╚══════════════════════════════════════════════════════════╝ */
async function fetchLatest() {
  if (appState.mode === 'demo') return;

  try {
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), CONFIG.CONNECT_TIMEOUT_MS);

    const [telemetryRes, trustRes] = await Promise.all([
      fetch(`${CONFIG.API_BASE}/api/telemetry/latest`, { signal: ctrl.signal }),
      fetch(`${CONFIG.API_BASE}/api/trust/latest`, { signal: ctrl.signal }),
    ]);

    clearTimeout(timeout);

    if (!telemetryRes.ok) throw new Error(`Telemetry HTTP ${telemetryRes.status}`);
    if (!trustRes.ok) throw new Error(`Trust HTTP ${trustRes.status}`);

    const telemetryRaw = await telemetryRes.json();
    const trustRaw = await trustRes.json();

    appState.lastRawPayload = {
      telemetry: telemetryRaw,
      trust: trustRaw,
    };

    const canonical = mapTrustPayload(trustRaw, telemetryRaw);
    if (!canonical) throw new Error('mapTrustPayload returned null');

    appState.data = canonical;
    appState.connected = true;
    appState.lastUpdated = new Date();

    appState.history.push({ ...canonical });
    if (appState.history.length > CONFIG.HISTORY_MAX) appState.history.shift();

    renderAll();
  } catch (err) {
    console.error('PulseTrust live request failed:', err);
    appState.connected = false;

    if (appState.data === null) {
      enterDemoMode();
    } else {
      renderHeader();
    }
  }
}

function startPolling() {
  clearInterval(appState.pollTimer);
  appState.pollTimer = setInterval(fetchLatest, CONFIG.POLL_INTERVAL_MS);
  fetchLatest();
}

function stopPolling() {
  clearInterval(appState.pollTimer);
  appState.pollTimer = null;
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  21. DEMO MODE                                           ║
   ╚══════════════════════════════════════════════════════════╝ */
function enterDemoMode() {
  stopPolling();
  appState.mode = 'demo';
  loadDemoScenario(appState.activeScenario);
}

async function loadDemoScenario(key) {
  const validScenarios = ['normal', 'sensor-failure', 'real-event'];
  if (!validScenarios.includes(key)) return;

  appState.activeScenario = key;

  document.querySelectorAll('.btn-scenario').forEach(btn => {
    const active = btn.dataset.scenario === key;
    btn.className = `btn-scenario ${active ? 'btn--cta' : 'btn--ghost'}`;
    btn.setAttribute('aria-pressed', String(active));
  });

  try {
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), CONFIG.CONNECT_TIMEOUT_MS);
    const res = await fetch(
      `${CONFIG.API_BASE}/api/trust/demo/${encodeURIComponent(key)}`,
      { signal: ctrl.signal }
    );
    clearTimeout(timeout);

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const raw = await res.json();
    const canonical = mapTrustPayload(raw);

    if (!canonical) throw new Error('mapTrustPayload returned null');

    appState.lastRawPayload = raw;
    appState.data = canonical;
    appState.connected = true;
    appState.lastUpdated = new Date();

    // Keep a short chart/timeline trail using real backend scenario results.
    appState.history.push({ ...canonical });
    if (appState.history.length > CONFIG.HISTORY_MAX) appState.history.shift();

    renderAll();
  } catch (err) {
    console.error('PulseTrust demo request failed:', err);
    appState.connected = false;
    renderHeader();
  }
}

function initDemoButtons() {
  document.querySelectorAll('.btn-scenario').forEach(btn => {
    btn.addEventListener('click', () => {
      if (appState.mode !== 'demo') return;
      loadDemoScenario(btn.dataset.scenario);
    });
  });
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  MASTER RENDER                                           ║
   ╚══════════════════════════════════════════════════════════╝ */

function renderCommandCenter() {
  const d = appState.data;
  if (!d) return;

  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  const t1 = d.telemetry?.temp_1;
  const t2 = d.telemetry?.temp_2;
  const s1 = d.sensor_1 ?? appState.lastRawPayload?.sensor_1 ?? appState.lastRawPayload?.trust?.sensor_1 ?? {};
  const s2 = d.sensor_2 ?? appState.lastRawPayload?.sensor_2 ?? appState.lastRawPayload?.trust?.sensor_2 ?? {};

  const agreement = d.agreement ?? appState.lastRawPayload?.agreement ?? appState.lastRawPayload?.trust?.agreement;
  const corroborated = d.corroborated_event ?? appState.lastRawPayload?.corroborated_event ?? appState.lastRawPayload?.trust?.corroborated_event;
  const anomalous = Boolean(d.anomaly_summary?.is_anomaly);

  setText('cmd-trust', d.state ?? '—');
  setText('cmd-agreement', agreement === true ? 'AGREE' : agreement === false ? 'DISAGREE' : '—');
  setText('cmd-event', corroborated === true ? 'CORROBORATED' : corroborated === false ? 'NONE' : '—');
  setText('cmd-anomaly', anomalous ? 'DETECTED' : 'CLEAR');

  setText('sensor1-value', t1 != null ? Number(t1).toFixed(2) : '—');
  setText('sensor2-value', t2 != null ? Number(t2).toFixed(2) : '—');
  setText('sensor1-trust', s1.trust_score != null ? `${Number(s1.trust_score).toFixed(0)}/100` : '—');
  setText('sensor2-trust', s2.trust_score != null ? `${Number(s2.trust_score).toFixed(0)}/100` : '—');
  setText('sensor1-anomaly', s1.anomaly === true ? 'ANOMALY' : s1.anomaly === false ? 'NORMAL' : '—');
  setText('sensor2-anomaly', s2.anomaly === true ? 'ANOMALY' : s2.anomaly === false ? 'NORMAL' : '—');
  setText('pair-agreement', agreement === true ? '✓ AGREE' : agreement === false ? '✕ DISAGREE' : '—');

  if (t1 != null && t2 != null) setText('pair-delta', `Δ ${Math.abs(Number(t1)-Number(t2)).toFixed(2)} °C`);
  else setText('pair-delta', 'Δ —');
}

function renderAll() {
  renderHeader();
  renderCommandCenter();
  renderHero();
  renderDigitalTwin();
  renderTelemetry();
  renderEvidence();
  renderBreakdown();
  renderDecision();
  renderAllCharts();
  renderTimeline();
  renderTechnicalDetails();
  chartModal.refresh();
}

/* ╔══════════════════════════════════════════════════════════╗
   ║  22. INIT                                                ║
   ╚══════════════════════════════════════════════════════════╝ */
document.addEventListener('DOMContentLoaded', () => {
  initScrollReveal();
  initDigitalTwin();
  initRangeControls();
  initTelemetryCardClicks();
  initTechnicalDetails();
  initDemoButtons();
  chartModal.init();

  // Start live connection; fall back to Demo Mode if backend unreachable
  startPolling();

  // Last-updated counter (refreshes every second)
  setInterval(() => {
    if (appState.data && appState.lastUpdated) renderHeader();
  }, 1000);
});

/* ╔══════════════════════════════════════════════════════════╗
   ║  UTILITIES                                               ║
   ╚══════════════════════════════════════════════════════════╝ */

/** Monoline icons, same stroke language as the fan twin */
const ICONS = {
  check: '<path d="M3 8.5l3.2 3.2L13 4.8"/>',
  cross: '<path d="M4 4l8 8M12 4l-8 8"/>',
  warn:  '<path d="M8 2.2L14.2 13H1.8L8 2.2Z"/><path d="M8 6.5v3M8 11.4v.1"/>',
  block: '<circle cx="8" cy="8" r="5.8"/><path d="M3.9 3.9l8.2 8.2"/>',
};
function icon(name, extra = '') {
  if (!ICONS[name]) return '';
  return `<svg class="icon ${extra}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[name]}</svg>`;
}

/** Set text content safely */
function setTxt(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text ?? '—';
}

/** Escape HTML to prevent XSS from any backend string */
function esc(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(String(str ?? '')));
  return d.innerHTML;
}

/** Map machine state to its CSS color variable */
function stateToColor(state) {
  switch (state) {
    case 'TRUSTED':
    case 'NORMAL':    return 'var(--state-trusted)';
    case 'DEGRADED':
    case 'CAUTION':
    case 'DEGRADING': return 'var(--state-caution)';
    case 'UNTRUSTED':
    case 'FAULT':
    case 'OFFLINE':   return 'var(--state-critical)';
    default:          return 'var(--color-slate)';
  }
}

/** Color for the radial ring (same mapping, kept explicit) */
function stateToRingColor(state) {
  switch (state) {
    case 'TRUSTED':
    case 'NORMAL':    return 'var(--state-trusted)';
    case 'DEGRADED':
    case 'CAUTION':
    case 'DEGRADING': return 'var(--state-caution)';
    case 'UNTRUSTED':
    case 'FAULT':
    case 'OFFLINE':   return 'var(--state-critical)';
    default:          return 'var(--color-mist)';
  }
}

/** Unused in render but kept for completeness */
function stateToClass(state) {
  switch (state) {
    case 'TRUSTED':
    case 'NORMAL':    return 'trusted';
    case 'DEGRADED':
    case 'CAUTION':
    case 'DEGRADING': return 'caution';
    case 'UNTRUSTED':
    case 'FAULT':
    case 'OFFLINE':   return 'critical';
    default:          return 'offline';
  }
}
