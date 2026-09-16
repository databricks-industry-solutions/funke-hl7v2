import React from 'react';

// Minimal single-series sparkline: 2px line over a faint area, no axes (a trend cue, not a plot).
export function Sparkline({ data, height = 72 }) {
  const w = 100; // viewBox width; scales to container via preserveAspectRatio=none
  if (!data || data.length < 2) {
    return <div className="spark-empty muted small">Waiting for data…</div>;
  }
  const max = Math.max(...data, 1);
  const step = w / (data.length - 1);
  const y = (v) => height - (v / max) * (height - 6) - 3;
  const pts = data.map((v, i) => `${i * step},${y(v)}`);
  const line = `M ${pts.join(' L ')}`;
  const area = `${line} L ${w},${height} L 0,${height} Z`;
  return (
    <svg
      className="spark"
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Message rate trend"
    >
      <path d={area} fill="var(--series-1)" opacity="0.12" />
      <path d={line} fill="none" stroke="var(--series-1)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
