import React, { useState, useEffect, useRef, useMemo } from 'react';
import { API_BASE } from '../App';
import { FlaskConical, Play, SlidersHorizontal, Layers } from 'lucide-react';

// Build the default param values for a template from its schema.
function defaultsFor(template) {
  const out = {};
  (template.params || []).forEach(p => { out[p.key] = p.default; });
  return out;
}

// Group a template's params by their `group` for sectioned rendering.
function groupParams(params) {
  const groups = {};
  (params || []).forEach(p => {
    (groups[p.group] ||= []).push(p);
  });
  return groups;
}

function ParamControl({ spec, value, onChange }) {
  const common = {
    className: 'form-control',
    value: value ?? spec.default,
    onChange: e => onChange(spec.key, e.target.value),
    title: spec.help || '',
  };
  if (spec.type === 'select') {
    return (
      <select {...common} className="form-control form-select">
        {spec.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  if (spec.type === 'time') {
    return <input type="time" {...common} />;
  }
  // number / int
  return (
    <input
      type="number"
      {...common}
      min={spec.min} max={spec.max}
      step={spec.step ?? (spec.type === 'int' ? 1 : 'any')}
      onChange={e => onChange(spec.key, e.target.value === '' ? '' : Number(e.target.value))}
    />
  );
}

export default function BacktestRunner({ onResult }) {
  const [templates, setTemplates] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  // Per-strategy param values, so switching strategies preserves edits.
  const [paramsById, setParamsById] = useState({});
  const [previewLegs, setPreviewLegs] = useState([]);

  const [config, setConfig] = useState({
    underlying: 'NIFTY',
    start_date: '2024-10-01',
    end_date: '2024-10-31',
    initial_capital: 1000000,
    lot_size: 25,
    granularity: '1min',
    slippage_pct: 0.05,
    commission_per_lot: 20,
  });
  const [underlyings, setUnderlyings] = useState(['NIFTY']);

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState('');
  const [error, setError] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const wsRef = useRef(null);

  useEffect(() => () => wsRef.current?.close(), []);

  // Load templates (all ready-made strategies) + underlyings.
  useEffect(() => {
    fetch(`${API_BASE}/api/strategies/templates`)
      .then(r => r.json())
      .then(data => {
        setTemplates(data);
        const init = {};
        data.forEach(t => { init[t.id] = defaultsFor(t); });
        setParamsById(init);
        if (data.length) setSelectedId(data[0].id);
      })
      .catch(err => setError(`Could not load strategies: ${err.message}`));

    fetch(`${API_BASE}/api/data/underlyings`)
      .then(r => r.json())
      .then(data => {
        if (data?.length) {
          setUnderlyings(data.map(d => d.name));
          setConfig(c => ({ ...c, underlying: data[0].name }));
        }
      })
      .catch(() => {});
  }, []);

  const selected = useMemo(
    () => templates.find(t => t.id === selectedId),
    [templates, selectedId]);
  const params = paramsById[selectedId] || {};

  const setParam = (key, val) => {
    setParamsById(prev => ({ ...prev, [selectedId]: { ...prev[selectedId], [key]: val } }));
  };
  const resetParams = () => {
    if (selected) setParamsById(prev => ({ ...prev, [selectedId]: defaultsFor(selected) }));
  };

  // Live leg preview reflecting the current adjustments (debounced).
  useEffect(() => {
    if (!selectedId) return;
    const h = setTimeout(() => {
      fetch(`${API_BASE}/api/strategies/templates/${selectedId}/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      })
        .then(r => r.json())
        .then(d => setPreviewLegs(d.preview_legs || []))
        .catch(() => setPreviewLegs(selected?.preview_legs || []));
    }, 250);
    return () => clearTimeout(h);
  }, [selectedId, params, selected]);

  const runBacktest = () => {
    if (!selectedId) { setError('Select a strategy first.'); return; }
    setRunning(true); setProgress(0); setStatusMsg('Connecting…');
    setError(null); setWarnings([]);

    const payload = { ...config, strategy_id: selectedId, params };
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws/backtest`);
    wsRef.current = ws;

    ws.onopen = () => { setStatusMsg('Running backtest…'); ws.send(JSON.stringify(payload)); };
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'progress') { setProgress(data.progress); setStatusMsg(data.message); }
      else if (data.type === 'result') {
        setProgress(100); setRunning(false);
        setWarnings(data.data.warnings || []);
        ws.close();
        onResult?.(data.data);
      } else if (data.type === 'error') { setError(data.message); setRunning(false); ws.close(); }
    };
    ws.onerror = () => {
      setError(`Could not reach the backtest server at ${API_BASE}. Is the backend running?`);
      setRunning(false);
    };
  };

  const grouped = selected ? groupParams(selected.params) : {};

  return (
    <div style={{ display: 'flex', gap: '16px', padding: '16px', height: '100%', boxSizing: 'border-box', overflow: 'hidden' }}>

      {/* ── Strategy picker ── */}
      <div className="panel" style={{ width: '260px', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Layers size={15} /> Strategies
        </div>
        <div style={{ overflowY: 'auto', padding: '8px' }}>
          {templates.map(t => (
            <button
              key={t.id}
              onClick={() => setSelectedId(t.id)}
              className={`strategy-item${t.id === selectedId ? ' active' : ''}`}
              style={{
                display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
                padding: '10px 12px', marginBottom: '4px', borderRadius: '6px',
                border: '1px solid ' + (t.id === selectedId ? 'var(--accent-blue)' : 'var(--border-color)'),
                background: t.id === selectedId ? 'rgba(59,130,246,0.12)' : 'var(--bg-tertiary)',
                color: 'var(--text-primary)',
              }}
            >
              <div style={{ fontSize: '13px', fontWeight: 600 }}>{t.name}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px', lineHeight: 1.35 }}>
                {t.description}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* ── Adjustments + legs ── */}
      <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div className="panel-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <SlidersHorizontal size={15} /> {selected ? `Adjust — ${selected.name}` : 'Adjust'}
          </span>
          <button className="btn btn-sm btn-ghost" onClick={resetParams} style={{ fontSize: '11px' }}>
            Reset defaults
          </button>
        </div>

        <div style={{ overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {Object.entries(grouped).map(([group, specs]) => (
            <div key={group}>
              <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-secondary)', marginBottom: '8px', fontWeight: 700 }}>
                {group}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '12px' }}>
                {specs.map(spec => (
                  <div key={spec.key} className="form-group" style={{ margin: 0 }}>
                    <label className="form-label" style={{ fontSize: '11px' }}>{spec.label}</label>
                    <ParamControl spec={spec} value={params[spec.key]} onChange={setParam} />
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* Live leg preview */}
          <div>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-secondary)', marginBottom: '8px', fontWeight: 700 }}>
              Legs at entry
            </div>
            {previewLegs.length ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {previewLegs.map((leg, i) => (
                  <span key={i} style={{
                    fontFamily: 'var(--font-mono)', fontSize: '12px', padding: '4px 10px', borderRadius: '4px',
                    border: '1px solid var(--border-color)',
                    background: leg.side === 'SELL' ? 'rgba(248,81,73,0.12)' : 'rgba(63,185,80,0.12)',
                    color: leg.side === 'SELL' ? 'var(--accent-red-light)' : 'var(--accent-green-light)',
                  }}>
                    {leg.side} {leg.lots}× {leg.option_type} {leg.strike}
                  </span>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                {selected?.category === 'Directional'
                  ? 'Directional strategy — legs are chosen at runtime from the signal.'
                  : 'No legs to preview.'}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Run configuration ── */}
      <div className="panel" style={{ width: '300px', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FlaskConical size={15} /> Run
        </div>
        <div style={{ overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Underlying</label>
            <select className="form-control form-select" value={config.underlying}
                    onChange={e => setConfig({ ...config, underlying: e.target.value })}>
              {underlyings.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div className="flex gap-4">
            <div className="form-group" style={{ flex: 1, margin: 0 }}>
              <label className="form-label">Start</label>
              <input type="date" className="form-control" value={config.start_date}
                     onChange={e => setConfig({ ...config, start_date: e.target.value })} />
            </div>
            <div className="form-group" style={{ flex: 1, margin: 0 }}>
              <label className="form-label">End</label>
              <input type="date" className="form-control" value={config.end_date}
                     onChange={e => setConfig({ ...config, end_date: e.target.value })} />
            </div>
          </div>
          <div className="flex gap-4">
            <div className="form-group" style={{ flex: 1, margin: 0 }}>
              <label className="form-label">Granularity</label>
              <select className="form-control form-select" value={config.granularity}
                      onChange={e => setConfig({ ...config, granularity: e.target.value })}>
                <option value="1min">1 min (intraday)</option>
                <option value="1d">1 day (EOD)</option>
              </select>
            </div>
            <div className="form-group" style={{ flex: 1, margin: 0 }}>
              <label className="form-label">Lot Size</label>
              <input type="number" className="form-control" value={config.lot_size}
                     onChange={e => setConfig({ ...config, lot_size: parseInt(e.target.value) || 1 })} />
            </div>
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Initial Capital (₹)</label>
            <input type="number" className="form-control" value={config.initial_capital}
                   onChange={e => setConfig({ ...config, initial_capital: parseInt(e.target.value) || 0 })} />
          </div>
          <div className="flex gap-4">
            <div className="form-group" style={{ flex: 1, margin: 0 }}>
              <label className="form-label">Slippage (%)</label>
              <input type="number" step="0.01" className="form-control" value={config.slippage_pct}
                     onChange={e => setConfig({ ...config, slippage_pct: parseFloat(e.target.value) || 0 })} />
            </div>
            <div className="form-group" style={{ flex: 1, margin: 0 }}>
              <label className="form-label">Comm./Lot (₹)</label>
              <input type="number" className="form-control" value={config.commission_per_lot}
                     onChange={e => setConfig({ ...config, commission_per_lot: parseInt(e.target.value) || 0 })} />
            </div>
          </div>

          <span className="text-muted" style={{ fontSize: '11px', lineHeight: 1.4 }}>
            Intraday strategies need 1-minute data. NIFTY/BANKNIFTY/SENSEX intraday
            covers Oct 2024 onward.
          </span>

          {error && (
            <div className="badge badge-red" style={{ padding: '8px', fontSize: '12px' }}>{error}</div>
          )}
          {warnings.length > 0 && (
            <div className="badge badge-yellow" style={{ padding: '8px', fontSize: '11px', lineHeight: 1.5 }}>
              {warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
            </div>
          )}
          {running && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '6px' }}>
                <span className="text-muted">{statusMsg}</span>
                <span className="text-blue">{progress}%</span>
              </div>
              <div style={{ width: '100%', height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden' }}>
                <div style={{ width: `${progress}%`, height: '100%', background: 'var(--accent-blue)', transition: 'width 0.3s' }} />
              </div>
            </div>
          )}

          <button className="btn btn-primary" onClick={runBacktest} disabled={running}
                  style={{ marginTop: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
            <Play size={14} /> {running ? 'Running…' : 'Run Backtest'}
          </button>
        </div>
      </div>
    </div>
  );
}
