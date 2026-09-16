import React, { useEffect, useRef, useState } from 'react';
import {
  getStatus,
  getCensus,
  start,
  stop,
  setPeakRate,
  setEmrWeights,
  getPipelines,
  pausePipelines,
  resumePipelines,
  getFlow,
  getFlowSample,
} from './api.js';
import { Sparkline } from './Sparkline.jsx';
import { FlowTab } from './FlowTab.jsx';

const POLL_MS = 2000;
const RATE_HISTORY = 60;
// Pipeline state transitions take minutes, so poll them on their own slower cadence rather than
// on the 2s status loop (each tick lists workspace pipelines).
const PIPE_POLL_MS = 5000;
// Flow metrics hit the SQL warehouse, so poll them only while the Data Flow tab is open.
const FLOW_POLL_MS = 5000;

const TRIGGERS = {
  A01: { label: 'Admit', slot: 'var(--series-1)' },
  A04: { label: 'Register', slot: 'var(--series-2)' },
  A02: { label: 'Transfer', slot: 'var(--series-3)' },
  A03: { label: 'Discharge', slot: 'var(--series-6)' },
};

// Fixed color per EMR (categorical slots 1–4), assigned by roster order.
const EMR_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)'];

const STATUS_META = {
  running: { label: 'Running', color: 'var(--good)' },
  seeding: { label: 'Seeding history…', color: 'var(--warning)' },
  stopped: { label: 'Stopped', color: 'var(--muted)' },
};

// Lakeflow PipelineState -> pill label/color. `transitioning` states disable the toggle.
const PIPE_STATE = {
  RUNNING: { label: 'Running', color: 'var(--good)' },
  IDLE: { label: 'Paused', color: 'var(--muted)' },
  STARTING: { label: 'Starting…', color: 'var(--warning)', transitioning: true },
  DEPLOYING: { label: 'Starting…', color: 'var(--warning)', transitioning: true },
  RESETTING: { label: 'Starting…', color: 'var(--warning)', transitioning: true },
  RECOVERING: { label: 'Recovering…', color: 'var(--warning)', transitioning: true },
  STOPPING: { label: 'Stopping…', color: 'var(--warning)', transitioning: true },
  FAILED: { label: 'Failed', color: 'var(--critical)' },
};

function utilColor(pct) {
  if (pct >= 90) return 'var(--critical)';
  if (pct >= 75) return 'var(--warning)';
  return 'var(--good)';
}

export default function App() {
  const [tab, setTab] = useState('control');
  const [status, setStatus] = useState(null);
  const [census, setCensus] = useState(null);
  const [rateHistory, setRateHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [peak, setPeak] = useState(400);
  const peakDirty = useRef(false);
  const [weights, setWeights] = useState({});
  const weightsDirty = useRef(false);
  const [pipelines, setPipelines] = useState(null);
  const [pipeBusy, setPipeBusy] = useState(false);
  const [flow, setFlow] = useState(null);
  const [sample, setSample] = useState(null);
  const [flowAt, setFlowAt] = useState(0);
  const [clock, setClock] = useState(Date.now());

  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const [s, c] = await Promise.all([getStatus(), getCensus()]);
        if (!alive) return;
        setStatus(s);
        setCensus(c);
        if (!peakDirty.current) setPeak(s.config.peak_rate_per_hour);
        if (!weightsDirty.current) setWeights(s.config.emr_weights || {});
        setRateHistory((h) => [...h, s.rate_per_hour].slice(-RATE_HISTORY));
      } catch (e) {
        /* transient; next tick retries */
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    async function pollPipes() {
      try {
        const p = await getPipelines();
        if (alive) setPipelines(p);
      } catch (e) {
        /* transient; next tick retries */
      }
    }
    pollPipes();
    const id = setInterval(pollPipes, PIPE_POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Flow metrics + sample: warehouse-backed, so only poll while the Data Flow tab is active.
  useEffect(() => {
    if (tab !== 'flow') return undefined;
    let alive = true;
    async function pollFlow() {
      try {
        const [f, sm] = await Promise.all([getFlow(), getFlowSample()]);
        if (!alive) return;
        setFlow(f);
        setSample(sm);
        setFlowAt(Date.now());
      } catch (e) {
        /* transient; next tick retries */
      }
    }
    pollFlow();
    const id = setInterval(pollFlow, FLOW_POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [tab]);

  // Local 1s ticker so "updated Ns ago" counts up smoothly between flow polls.
  useEffect(() => {
    if (tab !== 'flow') return undefined;
    const id = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(id);
  }, [tab]);

  const running = status && (status.status === 'running' || status.status === 'seeding');

  const pipeList = (pipelines && pipelines.pipelines) || [];
  const pipesRunning = pipeList.some((p) => p.state === 'RUNNING');
  const pipesTransitioning = pipeList.some((p) => (PIPE_STATE[p.state] || {}).transitioning);

  async function pipeToggle() {
    setPipeBusy(true);
    try {
      const p = pipesRunning ? await pausePipelines() : await resumePipelines();
      setPipelines(p);
    } finally {
      setPipeBusy(false);
    }
  }

  async function toggle() {
    setBusy(true);
    try {
      const s = running ? await stop() : await start();
      setStatus(s);
    } finally {
      setBusy(false);
    }
  }

  async function commitPeak(v) {
    setPeak(v);
    peakDirty.current = true;
    await setPeakRate(v);
    peakDirty.current = false;
  }

  async function setParts(code, value) {
    const next = { ...weights, [code]: Math.max(0, value) };
    weightsDirty.current = true;
    setWeights(next);
    await setEmrWeights(next);
    weightsDirty.current = false;
  }

  const meta = status ? STATUS_META[status.status] : STATUS_META.stopped;

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>HL7 Bed Utilization</h1>
          <p className="subtitle">Synthetic HL7v2 admit / discharge / transfer stream</p>
        </div>
        <div className="header-controls">
          <span className="pill" style={{ '--pill': meta.color }}>
            <span className="dot" /> {meta.label}
          </span>
          <button className={`toggle ${running ? 'stop' : 'go'}`} onClick={toggle} disabled={busy}>
            {running ? 'Stop' : 'Start'}
          </button>
        </div>
      </header>

      <nav className="tabs">
        <button
          className={`tab ${tab === 'control' ? 'active' : ''}`}
          onClick={() => setTab('control')}
        >
          Control Room
        </button>
        <button
          className={`tab ${tab === 'flow' ? 'active' : ''}`}
          onClick={() => setTab('flow')}
        >
          Data Flow
        </button>
        <button
          className={`tab ${tab === 'dashboard' ? 'active' : ''}`}
          onClick={() => setTab('dashboard')}
        >
          Dashboard
        </button>
      </nav>

      {/* Dashboard stays mounted across tab switches so the embed keeps its state; hidden via CSS. */}
      <section className="dashboard-pane" hidden={tab !== 'dashboard'}>
        {status && status.dashboard_url ? (
          <iframe
            className="dashboard-frame"
            src={status.dashboard_url}
            title="Hospital Bed Utilization dashboard"
          />
        ) : (
          <p className="muted">
            Dashboard unavailable — it may not be published yet, or embedding is not enabled for
            this workspace.
          </p>
        )}
      </section>

      <div hidden={tab !== 'flow'}>
        <FlowTab
          flow={flow}
          sample={sample}
          pipeList={pipeList}
          status={status}
          ageOffset={flowAt ? Math.max(0, Math.floor((clock - flowAt) / 1000)) : 0}
        />
      </div>

      <div hidden={tab !== 'control'}>
      {status && (
        <>
          <section className="tiles">
            <Tile
              label="Network utilization"
              value={census ? `${census.utilization}%` : '—'}
              accent={census ? utilColor(census.utilization) : undefined}
            />
            <Tile
              label="Occupied beds"
              value={census ? `${census.total_occupied}` : '—'}
              sub={census ? `of ${census.total_capacity}` : ''}
            />
            <Tile label="Messages this session" value={status.messages_written.toLocaleString()} />
            <Tile
              label="Live rate"
              value={`${status.rate_per_hour.toLocaleString()}`}
              sub="msg / hr"
            />
          </section>

          {status.status === 'seeding' && (
            <SeedingBar done={status.seeding.done} total={status.seeding.total} />
          )}

          <div className="grid">
            <section className="card">
              <h2>Message rate</h2>
              <Sparkline data={rateHistory} />
              <p className="muted small">Trailing {RATE_HISTORY * (POLL_MS / 1000)}s, msg/hr</p>
            </section>

            <section className="card">
              <h2>Event mix</h2>
              <EventMix counts={status.events_by_type} />
            </section>
          </div>

          <section className="card">
            <div className="card-head">
              <h2>Occupancy by facility</h2>
              <Legend />
            </div>
            {census && census.facilities.map((f) => <FacilityRow key={f.code} f={f} />)}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>EMR source mix</h2>
              <span className="muted small">
                Parts set how much of the admission mix each EMR gets
              </span>
            </div>
            <EmrMixer
              emrs={status.emrs || []}
              weights={weights}
              actual={status.events_by_source || {}}
              onSetParts={setParts}
            />
          </section>

          <div className="grid">
            <section className="card">
              <h2>Recent events</h2>
              <EventFeed recent={status.recent} emrs={status.emrs || []} />
            </section>

            <section className="card">
              <h2>Generation rate</h2>
              <label className="slider-label">
                Peak messages / hour: <strong>{Math.round(peak)}</strong>
              </label>
              <input
                type="range"
                min="20"
                max="800"
                step="20"
                value={peak}
                onChange={(e) => setPeak(Number(e.target.value))}
                onMouseUp={(e) => commitPeak(Number(e.target.value))}
                onTouchEnd={(e) => commitPeak(Number(e.target.value))}
              />
              <p className="muted small">
                Realtime pacing scales this by the diurnal/weekly curve (capped at one message
                every 120s overnight).
              </p>
              {status.dashboard_url && (
                <a className="dash-link" href={status.dashboard_url} target="_blank" rel="noreferrer">
                  Open analytics dashboard →
                </a>
              )}
            </section>
          </div>

          <Pipelines
            pipelines={pipeList}
            running={pipesRunning}
            busy={pipeBusy}
            transitioning={pipesTransitioning}
            onToggle={pipeToggle}
          />
        </>
      )}
      {!status && <p className="muted">Connecting…</p>}
      </div>
    </div>
  );
}

function Pipelines({ pipelines, running, busy, transitioning, onToggle }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2>Data pipelines</h2>
        <button
          className={`toggle ${running ? 'stop' : 'go'}`}
          onClick={onToggle}
          disabled={busy || transitioning || pipelines.length === 0}
        >
          {running ? 'Pause pipelines' : 'Resume pipelines'}
        </button>
      </div>
      {pipelines.length === 0 ? (
        <p className="muted small">No pipelines found — they may not be deployed yet.</p>
      ) : (
        <div className="pipes">
          {pipelines.map((p) => {
            const m = PIPE_STATE[p.state] || { label: p.state, color: 'var(--muted)' };
            return (
              <div className="pipe-row" key={p.key}>
                <span className="pipe-name">{p.name}</span>
                <span className="pill" style={{ '--pill': m.color }}>
                  <span className="dot" /> {m.label}
                </span>
              </div>
            );
          })}
        </div>
      )}
      <p className="muted small">
        Pause the continuous Lakeflow pipelines to idle serverless compute between demos. The
        generator keeps writing files while paused; Auto Loader ingests the backlog on resume.
      </p>
    </section>
  );
}

function Tile({ label, value, sub, accent }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value" style={accent ? { color: accent } : undefined}>
        {value}
      </div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}

function SeedingBar({ done, total }) {
  const pct = total ? Math.round((100 * done) / total) : 0;
  return (
    <div className="seeding">
      <div className="seeding-track">
        <div className="seeding-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="muted small">
        Seeding backdated history — {done.toLocaleString()} / {total.toLocaleString()} messages
      </span>
    </div>
  );
}

function FacilityRow({ f }) {
  return (
    <div className="fac">
      <div className="fac-name">
        <strong>{f.name}</strong>
        <span className="muted small">
          {f.occupied}/{f.capacity} · {f.kind}
        </span>
      </div>
      <div className="bar-track">
        <div
          className="bar-fill"
          style={{ width: `${Math.min(100, f.utilization)}%`, background: utilColor(f.utilization) }}
        />
      </div>
      <div className="fac-pct" style={{ color: utilColor(f.utilization) }}>
        {f.utilization}%
      </div>
    </div>
  );
}

function EventMix({ counts }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="mix">
      {Object.keys(TRIGGERS).map((k) => {
        const n = counts[k] || 0;
        return (
          <div className="mix-row" key={k}>
            <span className="badge" style={{ background: TRIGGERS[k].slot }}>
              {k}
            </span>
            <span className="mix-name">{TRIGGERS[k].label}</span>
            <div className="bar-track thin">
              <div
                className="bar-fill"
                style={{ width: `${(100 * n) / total}%`, background: TRIGGERS[k].slot }}
              />
            </div>
            <span className="mix-count tnum">{n.toLocaleString()}</span>
          </div>
        );
      })}
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      <span><i style={{ background: 'var(--good)' }} /> &lt;75%</span>
      <span><i style={{ background: 'var(--warning)' }} /> 75–90%</span>
      <span><i style={{ background: 'var(--critical)' }} /> ≥90%</span>
    </div>
  );
}

function EventFeed({ recent, emrs }) {
  if (!recent.length) return <p className="muted small">No events yet.</p>;
  const colorOf = {};
  const nameOf = {};
  emrs.forEach((e, i) => {
    colorOf[e.code] = EMR_COLORS[i % EMR_COLORS.length];
    nameOf[e.code] = e.display_name;
  });
  return (
    <ul className="feed">
      {recent.map((e, i) => {
        const t = TRIGGERS[e.trigger] || { label: e.trigger, slot: 'var(--muted)' };
        return (
          <li key={i}>
            <span className="badge" style={{ background: t.slot }}>
              {e.trigger}
            </span>
            <span className="feed-main">
              <strong>{t.label}</strong> · {e.facility}/{e.unit} rm {e.room}
              <span className="muted"> — {e.patient_name}</span>
            </span>
            <span className="src-tag" style={{ color: colorOf[e.source] || 'var(--muted)' }}>
              <i style={{ background: colorOf[e.source] || 'var(--muted)' }} />
              {nameOf[e.source] || e.source}
            </span>
            <span className="muted small tnum">{e.ts.slice(11)}</span>
          </li>
        );
      })}
    </ul>
  );
}

function EmrMixer({ emrs, weights, actual, onSetParts }) {
  const totalParts =
    emrs.reduce((s, e) => s + Math.round(Number(weights[e.code]) || 0), 0) || 1;
  const totalActual = Object.values(actual).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="mixer">
      {emrs.map((e, i) => {
        const color = EMR_COLORS[i % EMR_COLORS.length];
        const parts = Math.round(Number(weights[e.code]) || 0);
        const targetPct = Math.round((100 * parts) / totalParts);
        const live = Math.round((100 * (actual[e.code] || 0)) / totalActual);
        return (
          <div className="mixer-row" key={e.code}>
            <span className="mixer-name">
              <i className="swatch" style={{ background: color }} />
              {e.display_name}
            </span>
            <span className="mixer-stepper">
              <button
                type="button"
                onClick={() => onSetParts(e.code, parts - 1)}
                disabled={parts <= 0}
                aria-label={`Fewer parts for ${e.display_name}`}
              >
                −
              </button>
              <span className="mixer-parts tnum" style={{ color }}>
                {parts}
              </span>
              <button
                type="button"
                onClick={() => onSetParts(e.code, parts + 1)}
                aria-label={`More parts for ${e.display_name}`}
              >
                +
              </button>
            </span>
            <span className="mixer-target tnum">
              {parts}/{totalParts} ({targetPct}%)
            </span>
            <span className="mixer-live tnum muted">live {live}%</span>
          </div>
        );
      })}
      <p className="muted small">
        Parts set the relative mix of <strong>new admissions</strong> per EMR (e.g. 1 vs 2 parts =
        admitted half as often); “live” is the actual share of messages generated so far (existing
        patients keep their original source).
      </p>
    </div>
  );
}
