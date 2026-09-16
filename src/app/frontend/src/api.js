// Thin fetch wrappers around the FastAPI control API.

async function req(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const getStatus = () => req('/api/status');
export const getCensus = () => req('/api/census');
export const start = () => req('/api/start', { method: 'POST' });
export const stop = () => req('/api/stop', { method: 'POST' });
export const setPeakRate = (peak_rate_per_hour) =>
  req('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ peak_rate_per_hour }),
  });

export const setEmrWeights = (emr_weights) =>
  req('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ emr_weights }),
  });

export const getFlow = () => req('/api/flow');
export const getFlowSample = () => req('/api/flow/sample');

export const getPipelines = () => req('/api/pipelines');
export const pausePipelines = () => req('/api/pipelines/pause', { method: 'POST' });
export const resumePipelines = () => req('/api/pipelines/resume', { method: 'POST' });
