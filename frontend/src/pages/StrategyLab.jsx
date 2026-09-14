import React, { useState, useEffect, useRef } from 'react';
import { API_BASE } from '../App';
import { Play, Plus, X, Layers } from 'lucide-react';

// A fresh leg with sensible defaults.
const newLeg = (over = {}) => ({
  id: Math.random().toString(36).slice(2, 9),
  side: 'SELL', option_type: 'CE', moneyness: 'ATM', strike_offset: 0, lots: 1,
  stop_loss_pct: '', take_profit_pct: '', trailing_sl_pct: '', move_to_cost_at_pct: '',
  ...over,
});

const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));

const cell = { background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px 6px', borderRadius: '4px', outline: 'none', fontSize: '12px', width: '100%' };

export default function StrategyLab({ onResult }) {
  const [legs, setLegs] = useState([
    newLeg({ side: 'SELL', option_type: 'CE', stop_loss_pct: 30, take_profit_pct: 50, tag: 'ce' }),
    newLeg({ side: 'SELL', option_type: 'PE', stop_loss_pct: 30, take_profit_pct: 50, tag: 'pe' }),
  ]);
  const [settings, setSettings] = useState({
    name: 'My Strategy', entry_time: '09:20', square_off_time: '15:15',
    max_entries_per_day: 1, re_entry: false,
  });
  const [config, setConfig] = useState({
    underlying: 'NIFTY', start_date: '2024-10-01', end_date: '2024-10-31',
    initial_capital: 1000000, lot_size: 25, granularity: '1min',
    slippage_pct: 0.05, commission_per_lot: 20,
  });
  const [underlyings, setUnderlyings] = useState(['NIFTY']);

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState('');
  const [error, setError] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const wsRef = useRef(null);
  useEffect(() => () => wsRef.current?.close(), []);

  useEffect(() => {
    fetch(`${API_BASE}/api/data/underlyings`).then(r => r.json())
      .then(d => { if (d?.length) { setUnderlyings(d.map(u => u.name)); setConfig(c => ({ ...c, underlying: d[0].name })); } })
      .catch(() => {});
  }, []);

  const setLeg = (id, field, val) => setLegs(ls => ls.map(l => l.id === id ? { ...l, [field]: val } : l));
  const addLeg = () => setLegs(ls => [...ls, newLeg({ tag: `leg${ls.length + 1}` })]);
  const removeLeg = (id) => setLegs(ls => ls.filter(l => l.id !== id));

  const run = () => {
    if (!legs.length) { setError('Add at least one leg.'); return; }
    setRunning(true); setProgress(0); setStatusMsg('Connecting…'); setError(null); setWarnings([]);
    const custom_strategy = {
      name: settings.name,
      entry_time: settings.entry_time,
      square_off_time: settings.square_off_time,
      max_entries_per_day: Number(settings.max_entries_per_day) || 1,
      re_entry: settings.re_entry,
      legs: legs.map(l => ({
        side: l.side, option_type: l.option_type, moneyness: l.moneyness,
        strike_offset: Number(l.strike_offset) || 0, lots: Number(l.lots) || 1,
        stop_loss_pct: num(l.stop_loss_pct), take_profit_pct: num(l.take_profit_pct),
        trailing_sl_pct: num(l.trailing_sl_pct), move_to_cost_at_pct: num(l.move_to_cost_at_pct),
        tag: l.tag || '',
      })),
    };
    const ws = new WebSocket(`${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/backtest`);
    wsRef.current = ws;
    ws.onopen = () => { setStatusMsg('Running…'); ws.send(JSON.stringify({ ...config, custom_strategy })); };
    ws.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === 'progress') { setProgress(d.progress); setStatusMsg(d.message); }
      else if (d.type === 'result') { setProgress(100); setRunning(false); setWarnings(d.data.warnings || []); ws.close(); onResult?.(d.data); }
      else if (d.type === 'error') { setError(d.message); setRunning(false); ws.close(); }
    };
    ws.onerror = () => { setError(`Could not reach the backtest server at ${API_BASE}.`); setRunning(false); };
  };

  const th = { textAlign: 'left', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.4px', color: 'var(--text-secondary)', padding: '0 6px 6px', fontWeight: 700 };

  return (
    <div style={{ display: 'flex', gap: '16px', padding: '16px', height: '100%', boxSizing: 'border-box', overflow: 'hidden' }}>
      {/* Builder */}
      <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Layers size={15} /> Strategy Builder
        </div>
        <div style={{ overflow: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
          {/* Legs table */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-secondary)', fontWeight: 700 }}>Legs</span>
              <button className="btn btn-sm btn-primary" onClick={addLeg} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Plus size={13} /> Add Leg</button>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', minWidth: '760px', borderCollapse: 'collapse' }}>
                <thead><tr>
                  {['Side', 'Type', 'Strike', 'Off', 'Lots', 'SL %', 'TP %', 'Trail %', '→Cost %', ''].map((h, i) =>
                    <th key={i} style={th}>{h}</th>)}
                </tr></thead>
                <tbody>
                  {legs.map(l => (
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
            <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
              Each leg exits on its own SL / TP / trailing / move-to-cost. Leave a box blank to disable it.
            </div>
          </div>

          {/* Entry / exit timing */}
          <div>
            <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-secondary)', fontWeight: 700 }}>Entry & Exit</span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '12px', marginTop: '8px' }}>
              <Field label="Entry time"><input type="time" className="form-control" value={settings.entry_time} onChange={e => setSettings(s => ({ ...s, entry_time: e.target.value }))} /></Field>
              <Field label="Square-off time"><input type="time" className="form-control" value={settings.square_off_time} onChange={e => setSettings(s => ({ ...s, square_off_time: e.target.value }))} /></Field>
              <Field label="Max entries / day"><input type="number" min="1" className="form-control" value={settings.max_entries_per_day} onChange={e => setSettings(s => ({ ...s, max_entries_per_day: e.target.value }))} /></Field>
              <Field label="Re-entry">
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', height: '32px', fontSize: '13px' }}>
                  <input type="checkbox" checked={settings.re_entry} onChange={e => setSettings(s => ({ ...s, re_entry: e.target.checked }))} />
                  Re-enter after close
                </label>
              </Field>
            </div>
          </div>
        </div>
      </div>

      {/* Run panel */}
      <div className="panel" style={{ width: '300px', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        <div className="panel-header">Run</div>
        <div style={{ overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <Field label="Underlying"><select className="form-control form-select" value={config.underlying} onChange={e => setConfig(c => ({ ...c, underlying: e.target.value }))}>{underlyings.map(u => <option key={u}>{u}</option>)}</select></Field>
          <div className="flex gap-4">
            <Field label="Start" grow><input type="date" className="form-control" value={config.start_date} onChange={e => setConfig(c => ({ ...c, start_date: e.target.value }))} /></Field>
            <Field label="End" grow><input type="date" className="form-control" value={config.end_date} onChange={e => setConfig(c => ({ ...c, end_date: e.target.value }))} /></Field>
          </div>
          <div className="flex gap-4">
            <Field label="Lot size" grow><input type="number" className="form-control" value={config.lot_size} onChange={e => setConfig(c => ({ ...c, lot_size: parseInt(e.target.value) || 1 }))} /></Field>
            <Field label="Capital ₹" grow><input type="number" className="form-control" value={config.initial_capital} onChange={e => setConfig(c => ({ ...c, initial_capital: parseInt(e.target.value) || 0 }))} /></Field>
          </div>
          <div className="flex gap-4">
            <Field label="Slippage %" grow><input type="number" step="0.01" className="form-control" value={config.slippage_pct} onChange={e => setConfig(c => ({ ...c, slippage_pct: parseFloat(e.target.value) || 0 }))} /></Field>
            <Field label="Comm./lot" grow><input type="number" className="form-control" value={config.commission_per_lot} onChange={e => setConfig(c => ({ ...c, commission_per_lot: parseInt(e.target.value) || 0 }))} /></Field>
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
