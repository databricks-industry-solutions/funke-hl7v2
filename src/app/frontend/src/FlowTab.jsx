import React from 'react';

// Medallion stages, left to right. Colors reuse the shared categorical slots.
const STAGES = [
  { id: 'source', label: 'Source', sub: 'ADT generator', color: 'var(--series-1)' },
  { id: 'landing', label: 'Landing', sub: '/Volumes/…/landing', color: 'var(--series-3)' },
  { id: 'bronze', label: 'Bronze', sub: 'raw_messages', color: 'var(--series-2)' },
  { id: 'silver', label: 'Silver', sub: 'parsed_messages', color: 'var(--series-4)' },
  { id: 'gold', label: 'Gold', sub: 'adt_events', color: 'var(--series-6)' },
];

// A stage counts as "fresh" when it took rows recently — drives connector animation.
const FRESH_LIMIT = 120;

const GOLD_LABELS = {
  event_type: 'Event',
  source_system: 'Source EMR',
  event_ts: 'Event time',
  facility_code: 'Facility',
  unit: 'Unit',
  room: 'Room',
  bed: 'Bed',
  patient_class: 'Class',
  visit_number: 'Visit',
  patient_first_name: 'First name',
  patient_last_name: 'Last name',
  patient_sex: 'Sex',
};

function fmtAge(sec) {
  if (sec == null) return '—';
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

function ageTone(sec) {
  if (sec == null) return 'var(--muted)';
  if (sec < FRESH_LIMIT) return 'var(--good)';
  if (sec < 600) return 'var(--warning)';
  return 'var(--muted)';
}

export function FlowTab({ flow, sample, pipeList, status, ageOffset }) {
  const stages = (flow && flow.stages) || {};
  const pipeState = {};
  (pipeList || []).forEach((p) => {
    pipeState[p.key] = p.state;
  });
  const ingestRunning = pipeState.ingest === 'RUNNING';
  const goldRunning = pipeState.gold === 'RUNNING';
  const sourceLive = !!status && (status.status === 'running' || status.status === 'seeding');

  // Age counts up between 5s polls via the local ticker offset.
  const ageOf = (id) => {
    const base = stages[id] && stages[id].age_seconds;
    return base == null ? null : base + ageOffset;
  };
  const freshOf = (id) => {
    const s = stages[id];
    return !!s && ageOf(id) != null && ageOf(id) < FRESH_LIMIT && s.per_min > 0;
  };

  // Connector tone per hop. active = flowing; stale = owner running but no recent rows; idle = paused.
  function hopTone(owner, downstream) {
    if (owner === 'source') return sourceLive ? 'active' : 'idle';
    const running = owner === 'ingest' ? ingestRunning : goldRunning;
    if (!running) return 'idle';
    return freshOf(downstream) ? 'active' : 'stale';
  }
  const connectors = [
    hopTone('source', 'landing'),
    hopTone('ingest', 'bronze'),
    hopTone('ingest', 'silver'),
    hopTone('gold', 'gold'),
  ];

  // Landing buffer state derived from source liveness vs. bronze freshness.
  let landing;
  if (!sourceLive) landing = { value: 'Idle', tone: 'var(--muted)', note: 'generator stopped' };
  else if (ingestRunning && freshOf('bronze'))
    landing = { value: 'Flowing', tone: 'var(--good)', note: 'files ingesting' };
  else landing = { value: 'Buffering', tone: 'var(--warning)', note: 'files awaiting ingest' };

  function nodeBody(id) {
    if (id === 'source') {
      return (
        <>
          <BigValue value={status ? status.messages_written.toLocaleString() : '—'} />
          <div className="flow-chips">
            <Chip label={sourceLive ? 'Live' : 'Stopped'} tone={sourceLive ? 'var(--good)' : 'var(--muted)'} />
            <Chip label={`${status ? status.rate_per_hour.toLocaleString() : 0}/hr`} />
          </div>
        </>
      );
    }
    if (id === 'landing') {
      return (
        <>
          <BigValue value={landing.value} tone={landing.tone} />
          <div className="flow-chips">
            <span className="muted small">{landing.note}</span>
          </div>
        </>
      );
    }
    const s = stages[id];
    const age = ageOf(id);
    return (
      <>
        <BigValue value={s ? s.count.toLocaleString() : '—'} />
        <div className="flow-chips">
          <Chip label={fmtAge(age)} tone={ageTone(age)} />
          <Chip label={`${s ? s.per_min : 0}/min`} />
        </div>
      </>
    );
  }

  const unavailable = flow && flow.available === false;

  return (
    <div className="flow">
      {unavailable && (
        <p className="muted small">
          No SQL warehouse bound — showing generator and pipeline state only. Per-stage counts
          appear once the app is deployed with a warehouse.
        </p>
      )}
      {flow && flow.stale && <p className="muted small">Warehouse slow to respond — showing last known values.</p>}

      <div className="flow-row">
        {STAGES.map((st, i) => (
          <React.Fragment key={st.id}>
            <StageNode label={st.label} sub={st.sub} color={st.color}>
              {nodeBody(st.id)}
            </StageNode>
            {i < STAGES.length - 1 && <FlowConnector tone={connectors[i]} />}
          </React.Fragment>
        ))}
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Follow a message</h2>
          <span className="muted small">The newest message that reached gold, at each stage</span>
        </div>
        <MessageTrace sample={sample} />
      </section>
    </div>
  );
}

function StageNode({ label, sub, color, children }) {
  return (
    <div className="card flow-node" style={{ '--node': color }}>
      <div className="flow-node-head">
        <span className="flow-dot" />
        <span className="flow-node-label">{label}</span>
      </div>
      <div className="flow-node-sub muted small">{sub}</div>
      <div className="flow-node-body">{children}</div>
    </div>
  );
}

function FlowConnector({ tone }) {
  return (
    <div className={`flow-connector ${tone}`} aria-hidden="true">
      <span className="flow-arrow">›</span>
    </div>
  );
}

function BigValue({ value, tone }) {
  return (
    <div className="flow-value tnum" style={tone ? { color: tone } : undefined}>
      {value}
    </div>
  );
}

function Chip({ label, tone }) {
  return (
    <span className="pill flow-chip" style={tone ? { '--pill': tone } : undefined}>
      {tone && <span className="dot" />}
      {label}
    </span>
  );
}

function MessageTrace({ sample }) {
  if (!sample || sample.available === false)
    return <p className="muted small">Waiting for the warehouse…</p>;
  if (sample.empty) return <p className="muted small">No messages have reached gold yet.</p>;

  const segments = (sample.raw || '').split(/\r\n|\r|\n/).filter(Boolean);
  return (
    <div className="trace">
      <div className="trace-col">
        <h3>Raw HL7</h3>
        <pre className="trace-raw">{segments.join('\n')}</pre>
      </div>
      <div className="trace-col">
        <h3>Parsed fields</h3>
        <ul className="trace-fields">
          {(sample.parsed || []).map((f) => (
            <li key={f.address}>
              <span className="trace-addr tnum">{f.address}</span>
              <span className="trace-label muted">{f.label}</span>
              <span className="trace-val">{f.value || '—'}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="trace-col">
        <h3>Gold row · adt_events</h3>
        <ul className="trace-fields">
          {Object.keys(GOLD_LABELS).map((k) => (
            <li key={k}>
              <span className="trace-label muted">{GOLD_LABELS[k]}</span>
              <span className="trace-val">{sample.gold && sample.gold[k] != null ? sample.gold[k] : '—'}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
