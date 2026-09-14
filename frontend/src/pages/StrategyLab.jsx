import React, { useState, useEffect, useRef } from 'react';
import { API_BASE } from '../App';
import { Play, Plus, X, Layers, Save, Trash2 } from 'lucide-react';

const rid = () => Math.random().toString(36).slice(2, 9);
const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
const OPERATORS = ['<', '<=', '>', '>=', '=='];

const newLeg = (over = {}) => ({
  id: rid(), side: 'SELL', option_type: 'CE', moneyness: 'ATM', strike_offset: 0, lots: 1,
  stop_loss_pct: '', take_profit_pct: '', trailing_sl_pct: '', move_to_cost_at_pct: '', tag: '', ...over,
});
const newCond = (over = {}) => ({
  id: rid(), kind: 'indicator', indicator_name: 'RSI', period: 14, operator: '<', value: '', ...over,
});
// A case holds its own legs, entry timing/logic and exit logic.
const newCase = (name, over = {}) => ({
  id: rid(), name: name || 'Case 1', entry_time: '09:20', max_entries_per_day: 1, re_entry: false,
  legs: [
    newLeg({ side: 'SELL', option_type: 'CE', stop_loss_pct: 30, take_profit_pct: 50, tag: 'ce' }),
    newLeg({ side: 'SELL', option_type: 'PE', stop_loss_pct: 30, take_profit_pct: 50, tag: 'pe' }),
  ],
  entryConds: [], exitConds: [], ...over,
});

const cell = { background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px 6px', borderRadius: '4px', outline: 'none', fontSize: '12px', width: '100%' };
const cell2 = { ...cell, width: 'auto', padding: '5px 7px' };
const sectionLabel = { fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-secondary)', fontWeight: 700 };

export default function StrategyLab({ onResult }) {
  const [cases, setCases] = useState([newCase('Case 1')]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [settings, setSettings] = useState({ name: 'My Strategy', square_off_time: '15:15' });
  const [targets, setTargets] = useState({ overall_sl: '', overall_tp: '', daily_sl: '', daily_tp: '' });
  const [config, setConfig] = useState({
    underlying: 'NIFTY', start_date: '2024-10-01', end_date: '2024-10-31',
    initial_capital: 1000000, lot_size: 25, granularity: '1min', slippage_pct: 0.05, commission_per_lot: 20,
  });
  const [underlyings, setUnderlyings] = useState(['NIFTY']);
  const [indicators, setIndicators] = useState([]);
  const [saved, setSaved] = useState([]);
  const [currentId, setCurrentId] = useState(null);

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState('');
  const [error, setError] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const wsRef = useRef(null);
  useEffect(() => () => wsRef.current?.close(), []);

  const refreshSaved = () => fetch(`${API_BASE}/api/builder/strategies`).then(r => r.json()).then(d => setSaved(Array.isArray(d) ? d : [])).catch(() => {});
  useEffect(() => {
    fetch(`${API_BASE}/api/data/underlyings`).then(r => r.json())
      .then(d => { if (d?.length) { setUnderlyings(d.map(u => u.name)); setConfig(c => ({ ...c, underlying: d[0].name })); } }).catch(() => {});
    fetch(`${API_BASE}/api/indicators`).then(r => r.json()).then(d => setIndicators(Array.isArray(d) ? d : [])).catch(() => {});
    refreshSaved();
  }, []);

  const active = cases[activeIdx] || cases[0];
  // Update the active case.
  const setCase = (patch) => setCases(cs => cs.map((c, i) => i === activeIdx ? { ...c, ...patch } : c));
  const addCase = () => setCases(cs => { const n = [...cs, newCase(`Case ${cs.length + 1}`)]; return n; });
  const removeCase = (idx) => setCases(cs => {
    if (cs.length === 1) return cs;
    const n = cs.filter((_, i) => i !== idx);
    setActiveIdx(a => Math.max(0, Math.min(a, n.length - 1)));
    return n;
  });

  // Leg ops on the active case.
  const setLeg = (id, field, val) => setCase({ legs: active.legs.map(l => l.id === id ? { ...l, [field]: val } : l) });
  const addLeg = () => setCase({ legs: [...active.legs, newLeg({ tag: `leg${active.legs.length + 1}` })] });
  const removeLeg = (id) => setCase({ legs: active.legs.filter(l => l.id !== id) });

  const condToModel = (c) => c.kind === 'spot'
    ? { type: 'price', field: 'spot', operator: c.operator, value: Number(c.value) }
    : { type: 'indicator', indicator_name: c.indicator_name, params: { period: Number(c.period) || 14 }, input_field: 'close', operator: c.operator, value: Number(c.value) };

  const caseToPayload = (c) => ({
    name: c.name, entry_time: c.entry_time,
    max_entries_per_day: Number(c.max_entries_per_day) || 1, re_entry: c.re_entry,
    legs: c.legs.map(l => ({
      side: l.side, option_type: l.option_type, moneyness: l.moneyness,
      strike_offset: Number(l.strike_offset) || 0, lots: Number(l.lots) || 1,
      stop_loss_pct: num(l.stop_loss_pct), take_profit_pct: num(l.take_profit_pct),
      trailing_sl_pct: num(l.trailing_sl_pct), move_to_cost_at_pct: num(l.move_to_cost_at_pct), tag: l.tag || '',
    })),
    entry_conditions: c.entryConds.filter(x => x.value !== '').map(condToModel),
    exit_conditions: c.exitConds.filter(x => x.value !== '').map(condToModel),
  });

  const run = () => {
    if (!cases.length || !cases.some(c => c.legs.length)) { setError('Add at least one leg.'); return; }
    setRunning(true); setProgress(0); setStatusMsg('Connecting…'); setError(null); setWarnings([]);
    const custom_strategy = {
      name: settings.name, square_off_time: settings.square_off_time,
      cases: cases.map(caseToPayload),
      overall_stop_loss: num(targets.overall_sl), overall_take_profit: num(targets.overall_tp),
    };
    const daily = { max_loss_per_day: num(targets.daily_sl), max_profit_per_day: num(targets.daily_tp) };
    const ws = new WebSocket(`${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/backtest`);
    wsRef.current = ws;
    ws.onopen = () => { setStatusMsg('Running…'); ws.send(JSON.stringify({ ...config, ...daily, custom_strategy })); };
    ws.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === 'progress') { setProgress(d.progress); setStatusMsg(d.message); }
      else if (d.type === 'result') { setProgress(100); setRunning(false); setWarnings(d.data.warnings || []); ws.close(); onResult?.(d.data); }
      else if (d.type === 'error') { setError(d.message); setRunning(false); ws.close(); }
    };
    ws.onerror = () => { setError(`Could not reach the backtest server at ${API_BASE}.`); setRunning(false); };
  };

  // Save / load.
  const saveStrategy = () => {
    const payload = { cases, settings, targets, config };
    fetch(`${API_BASE}/api/builder/strategies`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: currentId, name: settings.name || 'Untitled', payload }) })
      .then(r => r.json()).then(rec => { setCurrentId(rec.id); refreshSaved(); }).catch(() => setError('Could not save.'));
  };
  const loadStrategy = (sid) => {
    if (!sid) return;
    fetch(`${API_BASE}/api/builder/strategies/${sid}`).then(r => r.json()).then(rec => {
      const p = rec.payload || {};
      if (Array.isArray(p.cases) && p.cases.length) { setCases(p.cases); setActiveIdx(0); }
      if (p.settings) setSettings(p.settings);
      if (p.targets) setTargets(p.targets);
      if (p.config) setConfig(c => ({ ...c, ...p.config }));
      setCurrentId(rec.id);
    }).catch(() => setError('Could not load.'));
  };
  const deleteStrategy = () => {
    if (!currentId) return;
    fetch(`${API_BASE}/api/builder/strategies/${currentId}`, { method: 'DELETE' }).then(() => { setCurrentId(null); refreshSaved(); }).catch(() => {});
  };

  const th = { textAlign: 'left', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.4px', color: 'var(--text-secondary)', padding: '0 6px 6px', fontWeight: 700 };

  return (
    <div style={{ display: 'flex', gap: '16px', padding: '16px', height: '100%', boxSizing: 'border-box', overflow: 'hidden' }}>
      {/* Builder */}
      <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'space-between' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><Layers size={15} /> Strategy Builder</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <select className="form-control form-select" style={{ fontSize: '12px', padding: '4px 8px', maxWidth: '160px' }} value={currentId || ''} onChange={e => loadStrategy(e.target.value)} title="Load a saved strategy">
              <option value="">My Strategies…</option>
              {saved.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button className="btn btn-sm btn-ghost" onClick={saveStrategy} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px' }}><Save size={13} /> {currentId ? 'Update' : 'Save'}</button>
            {currentId && <button className="btn btn-sm btn-ghost" onClick={deleteStrategy} title="Delete saved" style={{ padding: '4px 6px' }}><Trash2 size={13} /></button>}
          </div>
        </div>

        {/* Case tabs */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '8px 16px 0', flexWrap: 'wrap' }}>
          {cases.map((c, i) => (
            <div key={c.id} onClick={() => setActiveIdx(i)}
                 style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', padding: '5px 10px', borderRadius: '6px 6px 0 0',
                   border: '1px solid ' + (i === activeIdx ? 'var(--accent-blue)' : 'var(--border-color)'), borderBottom: 'none',
                   background: i === activeIdx ? 'rgba(59,130,246,0.12)' : 'var(--bg-tertiary)', fontSize: '12px', fontWeight: 600 }}>
              {c.name}
              {cases.length > 1 && <X size={11} onClick={(e) => { e.stopPropagation(); removeCase(i); }} style={{ opacity: 0.6 }} />}
            </div>
          ))}
          <button className="btn btn-sm btn-ghost" onClick={addCase} style={{ fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}><Plus size={12} /> Add Case</button>
        </div>

        <div style={{ overflow: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '18px', borderTop: '1px solid var(--border-color)' }}>
          {/* Case name + entry timing */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '12px' }}>
            <Field label="Case name"><input className="form-control" value={active.name} onChange={e => setCase({ name: e.target.value })} /></Field>
            <Field label="Entry time"><input type="time" className="form-control" value={active.entry_time} onChange={e => setCase({ entry_time: e.target.value })} /></Field>
            <Field label="Max entries / day"><input type="number" min="1" className="form-control" value={active.max_entries_per_day} onChange={e => setCase({ max_entries_per_day: e.target.value })} /></Field>
            <Field label="Re-entry"><label style={{ display: 'flex', alignItems: 'center', gap: '8px', height: '32px', fontSize: '13px' }}><input type="checkbox" checked={active.re_entry} onChange={e => setCase({ re_entry: e.target.checked })} /> After close</label></Field>
          </div>

          {/* Legs */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span style={sectionLabel}>Legs — {active.name}</span>
              <button className="btn btn-sm btn-primary" onClick={addLeg} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Plus size={13} /> Add Leg</button>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', minWidth: '760px', borderCollapse: 'collapse' }}>
                <thead><tr>{['Side', 'Type', 'Strike', 'Off', 'Lots', 'SL %', 'TP %', 'Trail %', '→Cost %', ''].map((h, i) => <th key={i} style={th}>{h}</th>)}</tr></thead>
                <tbody>
                  {active.legs.map(l => (
                    <tr key={l.id}>
                      <td style={{ padding: '3px' }}><select style={{ ...cell, color: l.side === 'SELL' ? 'var(--accent-red-light)' : 'var(--accent-green-light)' }} value={l.side} onChange={e => setLeg(l.id, 'side', e.target.value)}><option>BUY</option><option>SELL</option></select></td>
                      <td style={{ padding: '3px' }}><select style={cell} value={l.option_type} onChange={e => setLeg(l.id, 'option_type', e.target.value)}><option>CE</option><option>PE</option></select></td>
                      <td style={{ padding: '3px' }}><select style={cell} value={l.moneyness} onChange={e => setLeg(l.id, 'moneyness', e.target.value)}><option>ATM</option><option>OTM</option><option>ITM</option></select></td>
                      <td style={{ padding: '3px', width: '52px' }}><input type="number" min="0" style={cell} value={l.strike_offset} disabled={l.moneyness === 'ATM'} onChange={e => setLeg(l.id, 'strike_offset', e.target.value)} /></td>
                      <td style={{ padding: '3px', width: '56px' }}><input type="number" min="1" style={cell} value={l.lots} onChange={e => setLeg(l.id, 'lots', e.target.value)} /></td>
                      <td style={{ padding: '3px', width: '62px' }}><input type="number" placeholder="—" style={cell} value={l.stop_loss_pct} onChange={e => setLeg(l.id, 'stop_loss_pct', e.target.value)} /></td>
                      <td style={{ padding: '3px', width: '62px' }}><input type="number" placeholder="—" style={cell} value={l.take_profit_pct} onChange={e => setLeg(l.id, 'take_profit_pct', e.target.value)} /></td>
                      <td style={{ padding: '3px', width: '62px' }}><input type="number" placeholder="—" style={cell} value={l.trailing_sl_pct} onChange={e => setLeg(l.id, 'trailing_sl_pct', e.target.value)} title="Trailing stop: exit if profit falls this many % from its peak" /></td>
                      <td style={{ padding: '3px', width: '62px' }}><input type="number" placeholder="—" style={cell} value={l.move_to_cost_at_pct} onChange={e => setLeg(l.id, 'move_to_cost_at_pct', e.target.value)} title="Move stop to breakeven once profit reaches this %" /></td>
                      <td style={{ padding: '3px' }}><button className="btn btn-sm btn-ghost" onClick={() => removeLeg(l.id)} style={{ padding: '2px 6px' }}><X size={13} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '6px' }}>Each leg exits on its own SL / TP / trailing / move-to-cost. Leave a box blank to disable it.</div>
          </div>

          <ConditionList title="Entry When (all true)" conditions={active.entryConds} setConditions={fn => setCase({ entryConds: typeof fn === 'function' ? fn(active.entryConds) : fn })} indicators={indicators}
            hint="Extra gate on top of the entry time for this case. Leave empty to enter purely on time." />
          <ConditionList title="Exit When (any true)" conditions={active.exitConds} setConditions={fn => setCase({ exitConds: typeof fn === 'function' ? fn(active.exitConds) : fn })} indicators={indicators}
            hint="Square off this case as soon as any condition triggers (per-leg stops and square-off time still apply)." />
        </div>
      </div>

      {/* Run panel */}
      <div className="panel" style={{ width: '300px', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        <div className="panel-header">Run</div>
        <div style={{ overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <Field label="Strategy name"><input className="form-control" value={settings.name} onChange={e => setSettings(s => ({ ...s, name: e.target.value }))} /></Field>
          <Field label="Underlying"><select className="form-control form-select" value={config.underlying} onChange={e => setConfig(c => ({ ...c, underlying: e.target.value }))}>{underlyings.map(u => <option key={u}>{u}</option>)}</select></Field>
          <div className="flex gap-4">
            <Field label="Start" grow><input type="date" className="form-control" value={config.start_date} onChange={e => setConfig(c => ({ ...c, start_date: e.target.value }))} /></Field>
            <Field label="End" grow><input type="date" className="form-control" value={config.end_date} onChange={e => setConfig(c => ({ ...c, end_date: e.target.value }))} /></Field>
          </div>
          <div className="flex gap-4">
            <Field label="Square-off" grow><input type="time" className="form-control" value={settings.square_off_time} onChange={e => setSettings(s => ({ ...s, square_off_time: e.target.value }))} /></Field>
            <Field label="Lot size" grow><input type="number" className="form-control" value={config.lot_size} onChange={e => setConfig(c => ({ ...c, lot_size: parseInt(e.target.value) || 1 }))} /></Field>
          </div>
          <Field label="Capital ₹"><input type="number" className="form-control" value={config.initial_capital} onChange={e => setConfig(c => ({ ...c, initial_capital: parseInt(e.target.value) || 0 }))} /></Field>
          <div className="flex gap-4">
            <Field label="Slippage %" grow><input type="number" step="0.01" className="form-control" value={config.slippage_pct} onChange={e => setConfig(c => ({ ...c, slippage_pct: parseFloat(e.target.value) || 0 }))} /></Field>
            <Field label="Comm./lot" grow><input type="number" className="form-control" value={config.commission_per_lot} onChange={e => setConfig(c => ({ ...c, commission_per_lot: parseInt(e.target.value) || 0 }))} /></Field>
          </div>

          <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
            <span style={sectionLabel}>Targets (₹)</span>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '8px' }}>
              <Field label="Per-trade SL"><input type="number" placeholder="—" className="form-control" value={targets.overall_sl} onChange={e => setTargets(t => ({ ...t, overall_sl: e.target.value }))} /></Field>
              <Field label="Per-trade TP"><input type="number" placeholder="—" className="form-control" value={targets.overall_tp} onChange={e => setTargets(t => ({ ...t, overall_tp: e.target.value }))} /></Field>
              <Field label="Daily SL"><input type="number" placeholder="—" className="form-control" value={targets.daily_sl} onChange={e => setTargets(t => ({ ...t, daily_sl: e.target.value }))} /></Field>
              <Field label="Daily TP"><input type="number" placeholder="—" className="form-control" value={targets.daily_tp} onChange={e => setTargets(t => ({ ...t, daily_tp: e.target.value }))} /></Field>
            </div>
          </div>

          <span className="text-muted" style={{ fontSize: '11px', lineHeight: 1.4 }}>Intraday data covers Oct 2024 onward (NIFTY / BANKNIFTY / SENSEX).</span>
          {error && <div className="badge badge-red" style={{ padding: '8px', fontSize: '12px' }}>{error}</div>}
          {warnings.length > 0 && <div className="badge badge-yellow" style={{ padding: '8px', fontSize: '11px', lineHeight: 1.5 }}>{warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}</div>}
          {running && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '6px' }}><span className="text-muted">{statusMsg}</span><span className="text-blue">{progress}%</span></div>
              <div style={{ width: '100%', height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden' }}><div style={{ width: `${progress}%`, height: '100%', background: 'var(--accent-blue)', transition: 'width 0.3s' }} /></div>
            </div>
          )}
          <button className="btn btn-primary" onClick={run} disabled={running} style={{ marginTop: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}><Play size={14} /> {running ? 'Running…' : 'Run Backtest'}</button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children, grow }) {
  return (
    <div className="form-group" style={{ margin: 0, flex: grow ? 1 : undefined }}>
      <label className="form-label" style={{ fontSize: '11px' }}>{label}</label>
      {children}
    </div>
  );
}

function ConditionList({ title, conditions, setConditions, indicators, hint }) {
  const set = (id, field, val) => setConditions(cs => cs.map(c => c.id === id ? { ...c, [field]: val } : c));
  const add = () => setConditions(cs => [...cs, newCond()]);
  const remove = (id) => setConditions(cs => cs.filter(c => c.id !== id));
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <span style={sectionLabel}>{title}</span>
        <button className="btn btn-sm btn-ghost" onClick={add} style={{ fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}><Plus size={12} /> Add condition</button>
      </div>
      {conditions.length === 0 ? (
        <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>{hint}</div>
      ) : conditions.map(c => (
        <div key={c.id} style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '6px', flexWrap: 'wrap' }}>
          <select style={cell2} value={c.kind} onChange={e => set(c.id, 'kind', e.target.value)}>
            <option value="indicator">Indicator</option>
            <option value="spot">Spot price</option>
          </select>
          {c.kind === 'indicator' && (
            <>
              <select style={{ ...cell2, minWidth: '90px' }} value={c.indicator_name} onChange={e => set(c.id, 'indicator_name', e.target.value)}>
                {(indicators.length ? indicators.map(i => i.name) : ['RSI', 'SMA', 'EMA', 'VWAP']).map(n => <option key={n} value={n}>{n}</option>)}
              </select>
              <input type="number" style={{ ...cell2, width: '58px' }} title="Period" value={c.period} onChange={e => set(c.id, 'period', e.target.value)} />
            </>
          )}
          <select style={{ ...cell2, width: '54px' }} value={c.operator} onChange={e => set(c.id, 'operator', e.target.value)}>{OPERATORS.map(o => <option key={o} value={o}>{o}</option>)}</select>
          <input type="number" placeholder="value" style={{ ...cell2, width: '80px' }} value={c.value} onChange={e => set(c.id, 'value', e.target.value)} />
          <button className="btn btn-sm btn-ghost" onClick={() => remove(c.id)} style={{ padding: '2px 6px' }}><X size={13} /></button>
        </div>
      ))}
    </div>
  );
}
