import React, { useState, useEffect, useRef } from 'react';
import { API_BASE } from '../App';

export default function BacktestRunner({ onResult }) {
  const [config, setConfig] = useState({
    underlying: 'NIFTY',
    start_date: '2022-01-01',
    end_date: '2022-01-31',
    initial_capital: 1000000,
    lot_size: 50,
    granularity: '1min',
    slippage_pct: 0.05,
    commission_per_lot: 20
  });

  const [savedStrategies, setSavedStrategies] = useState([]);
  const [selectedStrategy, setSelectedStrategy] = useState('');

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState('');
  const [error, setError] = useState(null);
  const [warnings, setWarnings] = useState([]);

  const [underlyings, setUnderlyings] = useState(['NIFTY']);
  const wsRef = useRef(null);

  // Don't leave a socket open if the user navigates away mid-run.
  useEffect(() => () => wsRef.current?.close(), []);

  useEffect(() => {
    // Load built-in examples
    fetch(`${API_BASE}/api/strategies/examples`)
      .then(res => res.json())
      .then(data => {
        setSavedStrategies(data);
        if (data.length > 0) setSelectedStrategy(data[0].id);
      })
      .catch(err => console.error(err));
      
    // Load dynamic underlyings
    fetch(`${API_BASE}/api/data/underlyings`)
      .then(res => res.json())
      .then(data => {
        if (data && data.length > 0) {
          const names = data.map(d => d.name);
          setUnderlyings(names);
          setConfig(c => ({ ...c, underlying: names[0] }));
        }
      })
      .catch(err => console.error(err));
  }, []);

  const runBacktest = () => {
    if (!selectedStrategy) {
      setError('Select a strategy first.');
      return;
    }

    setRunning(true);
    setProgress(0);
    setStatusMsg('Connecting...');
    setError(null);
    setWarnings([]);

    // The engine resolves `strategy_id` against its built-in and saved
    // strategies, so only the id travels over the wire.
    const payload = { ...config, strategy_id: selectedStrategy };

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${wsProtocol}//${window.location.hostname}:8000/ws/backtest`);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatusMsg('Running backtest...');
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'progress') {
        setProgress(data.progress);
        setStatusMsg(data.message);
      } else if (data.type === 'result') {
        setProgress(100);
        setRunning(false);
        setWarnings(data.data.warnings || []);
        ws.close();
        onResult?.(data.data);
      } else if (data.type === 'error') {
        setError(data.message);
        setRunning(false);
        ws.close();
      }
    };

    ws.onerror = () => {
      setError(`Could not reach the backtest server at ${API_BASE}. Is the backend running?`);
      setRunning(false);
    };
  };

  return (
    <div className="workspace" style={{ alignItems: 'center' }}>
      <div className="panel" style={{ width: '600px', marginTop: '40px' }}>
        <div className="panel-header">Backtest Configuration</div>
        
        <div className="panel-content flex-col gap-4">
          <div className="form-group">
            <label className="form-label">Strategy</label>
            <select className="form-control form-select" value={selectedStrategy} onChange={e => setSelectedStrategy(e.target.value)}>
              {savedStrategies.map(s => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            <span className="text-muted" style={{ fontSize: '11px', marginTop: '4px' }}>
              To backtest your own legs, build them on the Terminal tab and use Run Backtest there.
            </span>
          </div>

          <div className="flex gap-4">
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Underlying</label>
              <select className="form-control form-select" value={config.underlying} onChange={e => setConfig({...config, underlying: e.target.value})}>
                {underlyings.map(u => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Initial Capital (₹)</label>
              <input type="number" className="form-control" value={config.initial_capital} onChange={e => setConfig({...config, initial_capital: parseInt(e.target.value)})} />
            </div>
          </div>
          
          <div className="flex gap-4">
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Start Date</label>
              <input type="date" className="form-control" value={config.start_date} onChange={e => setConfig({...config, start_date: e.target.value})} />
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">End Date</label>
              <input type="date" className="form-control" value={config.end_date} onChange={e => setConfig({...config, end_date: e.target.value})} />
            </div>
          </div>
          
          <div className="flex gap-4">
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Slippage (%)</label>
              <input type="number" className="form-control" step="0.01" value={config.slippage_pct} onChange={e => setConfig({...config, slippage_pct: parseFloat(e.target.value)})} />
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Commission/Lot (₹)</label>
              <input type="number" className="form-control" value={config.commission_per_lot} onChange={e => setConfig({...config, commission_per_lot: parseInt(e.target.value) || 0})} />
            </div>
          </div>

          <div className="flex gap-4">
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Granularity</label>
              <select className="form-control form-select" value={config.granularity} onChange={e => setConfig({...config, granularity: e.target.value})}>
                <option value="1min">1 minute (intraday)</option>
                <option value="1d">1 day (EOD)</option>
              </select>
              <span className="text-muted" style={{ fontSize: '11px', marginTop: '4px' }}>
                Time-of-day rules (e.g. enter at 09:20) need 1-minute data — daily
                candles carry no intraday clock.
              </span>
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Lot Size</label>
              <input type="number" className="form-control" value={config.lot_size} onChange={e => setConfig({...config, lot_size: parseInt(e.target.value) || 1})} />
            </div>
          </div>

          {error && (
            <div className="badge badge-red" style={{ padding: '8px', fontSize: '13px' }}>
              Error: {error}
            </div>
          )}

          {warnings.length > 0 && (
            <div className="badge badge-yellow" style={{ padding: '8px', fontSize: '12px', lineHeight: 1.5 }}>
              {warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
            </div>
          )}

          {running && (
            <div className="mt-4">
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '12px' }}>
                <span className="text-muted">{statusMsg || 'Running Backtest...'}</span>
                <span className="text-blue">{progress}%</span>
              </div>
              <div style={{ width: '100%', height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden' }}>
                <div style={{ width: `${progress}%`, height: '100%', background: 'var(--accent-blue)', transition: 'width 0.3s' }}></div>
              </div>
            </div>
          )}

          <div className="mt-4 flex justify-between items-center">
            <div className="text-muted" style={{ fontSize: '12px' }}>
              Requires historical intraday data for the selected period.
            </div>
            <button className="btn btn-primary" style={{ padding: '8px 24px' }} onClick={runBacktest} disabled={running}>
              {running ? 'Processing...' : '▶ Run Backtest'}
            </button>
          </div>
          
        </div>
      </div>
    </div>
  );
}
