import React, { useState, useEffect, useRef } from 'react';
import { X, Play, Activity } from 'lucide-react';
import { createChart, LineSeries } from 'lightweight-charts';

export default function BacktestModal({ isOpen, onClose, legs, underlying, onResult }) {
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  
  const chartContainerRef = useRef(null);
  const chartInstance = useRef(null);

  // Form State
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-03-31');
  const [capital, setCapital] = useState(1000000);
  const [entryTime, setEntryTime] = useState('09:20');
  const [exitTime, setExitTime] = useState('15:15');
  const [stopLossPct, setStopLossPct] = useState('');

  useEffect(() => {
    if (!isOpen) {
      // Reset state on close
      setResult(null);
      setProgress(0);
      setStatusMsg('');
      setError(null);
      if (chartInstance.current) {
        chartInstance.current.remove();
        chartInstance.current = null;
      }
    }
  }, [isOpen]);

  useEffect(() => {
    if (result && chartContainerRef.current) {
      if (chartInstance.current) {
        chartInstance.current.remove();
      }
      
      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: 'solid', color: 'transparent' },
          textColor: '#8b949e',
        },
        grid: {
          vertLines: { color: 'rgba(48, 54, 61, 0.5)' },
          horzLines: { color: 'rgba(48, 54, 61, 0.5)' },
        },
        rightPriceScale: {
          borderVisible: false,
        },
        timeScale: {
          borderVisible: false,
          timeVisible: true,
        },
        width: chartContainerRef.current.clientWidth,
        height: 250,
      });

      const lineSeries = chart.addSeries(LineSeries, {
        color: '#3fb950',
        lineWidth: 2,
      });

      const data = result.equity_curve.map(p => ({
        time: new Date(p.timestamp).getTime() / 1000,
        value: p.value,
      }));

      lineSeries.setData(data);
      chart.timeScale().fitContent();
      chartInstance.current = chart;
    }
  }, [result]);

  const handleRun = () => {
    if (legs.length === 0) {
      setError("Please add at least one leg in the Strategy Builder.");
      return;
    }
    
    setLoading(true);
    setResult(null);
    setError(null);
    setProgress(0);

    // Build Entry Rule
    const entryRules = [{
      name: "Time Entry",
      condition: {
        type: "time",
        operator: "==",
        value: entryTime,
      },
      orders: legs.map(l => ({
        side: l.side,
        option_type: l.type,
        strike_selection: "FIXED",
        fixed_strike: l.strike,
        quantity: l.qty,
        expiry_selection: "nearest",
        tag: "LEG"
      })),
      max_triggers_per_day: 1
    }];

    // Build Exit Rules
    const exitRules = [{
      name: "Time Exit",
      condition: {
        type: "time",
        operator: ">=",
        value: exitTime,
      },
      max_triggers_per_day: 1
    }];

    if (stopLossPct) {
      exitRules.push({
        name: "Stop Loss",
        condition: {
          type: "price",
          field: "position_pnl_pct",
          operator: "<=",
          value: -parseFloat(stopLossPct)
        },
        max_triggers_per_day: 1
      });
    }

    const payload = {
      underlying: underlying || "NIFTY",
      start_date: startDate,
      end_date: endDate,
      initial_capital: parseFloat(capital),
      lot_size: 50,
      granularity: "1min",
      slippage_pct: 0.05,
      commission_per_lot: 20,
      strategy: {
        name: "Custom Strategy",
        description: "Built via Strategy Builder",
        entry_rules: entryRules,
        exit_rules: exitRules,
        square_off_time: exitTime,
        max_positions: 10
      }
    };

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.hostname}:8000/ws/backtest`;
    
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'progress') {
        setProgress(data.progress);
        setStatusMsg(data.message);
      } else if (data.type === 'result') {
        setResult(data.data);
        setLoading(false);
        ws.close();
      } else if (data.type === 'error') {
        setError(data.message);
        setLoading(false);
        ws.close();
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection failed.");
      setLoading(false);
    };
  };

  if (!isOpen) return null;

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.7)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: '900px', maxHeight: '90vh', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '8px', display: 'flex', flexDirection: 'column', boxShadow: '0 10px 30px rgba(0,0,0,0.5)' }}>
        
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-tertiary)', borderTopLeftRadius: '8px', borderTopRightRadius: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 'bold' }}>
            <Activity size={20} color="var(--accent-blue)" />
            Run Backtest
          </div>
          <button className="btn btn-ghost" onClick={onClose}><X size={20} /></button>
        </div>

        {/* Content */}
        <div style={{ padding: '24px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {!result && !loading && (
            <div style={{ display: 'flex', gap: '24px' }}>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ fontWeight: 'bold', color: 'var(--text-secondary)' }}>Backtest Configuration</div>
                
                <div style={{ display: 'flex', gap: '16px' }}>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: 'var(--text-muted)' }}>Start Date</label>
                    <input type="date" style={{ width: '100%', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '8px', borderRadius: '4px', outline: 'none' }} value={startDate} onChange={e => setStartDate(e.target.value)} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: 'var(--text-muted)' }}>End Date</label>
                    <input type="date" style={{ width: '100%', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '8px', borderRadius: '4px', outline: 'none' }} value={endDate} onChange={e => setEndDate(e.target.value)} />
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: 'var(--text-muted)' }}>Initial Capital</label>
                  <input type="number" style={{ width: '100%', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '8px', borderRadius: '4px', outline: 'none' }} value={capital} onChange={e => setCapital(e.target.value)} />
                </div>
              </div>

              <div style={{ width: '1px', backgroundColor: 'var(--border-color)' }}></div>

              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ fontWeight: 'bold', color: 'var(--text-secondary)' }}>Execution Rules</div>
                
                <div style={{ display: 'flex', gap: '16px' }}>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: 'var(--text-muted)' }}>Entry Time</label>
                    <input type="time" style={{ width: '100%', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '8px', borderRadius: '4px', outline: 'none' }} value={entryTime} onChange={e => setEntryTime(e.target.value)} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: 'var(--text-muted)' }}>Exit Time</label>
                    <input type="time" style={{ width: '100%', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '8px', borderRadius: '4px', outline: 'none' }} value={exitTime} onChange={e => setExitTime(e.target.value)} />
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: 'var(--text-muted)' }}>Stop Loss % (Optional)</label>
                  <input type="number" placeholder="e.g. 20 for 20%" style={{ width: '100%', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '8px', borderRadius: '4px', outline: 'none' }} value={stopLossPct} onChange={e => setStopLossPct(e.target.value)} />
                </div>
              </div>
            </div>
          )}

          {error && <div style={{ padding: '16px', backgroundColor: 'rgba(248, 81, 73, 0.1)', color: 'var(--accent-red)', borderRadius: '4px', border: '1px solid var(--accent-red-dark)' }}>{error}</div>}

          {loading && (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '16px' }}>
              <div style={{ width: '300px', height: '8px', backgroundColor: 'var(--bg-tertiary)', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${progress}%`, height: '100%', backgroundColor: 'var(--accent-blue)', transition: 'width 0.2s' }}></div>
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '14px', fontFamily: 'var(--font-mono)' }}>{progress.toFixed(1)}% - {statusMsg}</div>
            </div>
          )}

          {result && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {/* KPIs */}
              <div style={{ display: 'flex', gap: '16px' }}>
                <div style={{ flex: 1, padding: '16px', backgroundColor: 'var(--bg-tertiary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Total P&L</div>
                  <div style={{ fontSize: '24px', fontWeight: 'bold', color: result.total_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                    ₹{result.total_pnl.toLocaleString()}
                  </div>
                </div>
                <div style={{ flex: 1, padding: '16px', backgroundColor: 'var(--bg-tertiary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Win Rate</div>
                  <div style={{ fontSize: '24px', fontWeight: 'bold', color: 'var(--text-primary)' }}>
                    {result.win_rate.toFixed(1)}%
                  </div>
                </div>
                <div style={{ flex: 1, padding: '16px', backgroundColor: 'var(--bg-tertiary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Max Drawdown</div>
                  <div style={{ fontSize: '24px', fontWeight: 'bold', color: 'var(--accent-red-light)' }}>
                    {result.max_drawdown_pct.toFixed(1)}%
                  </div>
                </div>
                <div style={{ flex: 1, padding: '16px', backgroundColor: 'var(--bg-tertiary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Sharpe Ratio</div>
                  <div style={{ fontSize: '24px', fontWeight: 'bold', color: 'var(--accent-blue-light)' }}>
                    {result.sharpe_ratio.toFixed(2)}
                  </div>
                </div>
              </div>

              {/* Chart */}
              <div style={{ padding: '16px', backgroundColor: 'var(--bg-tertiary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '16px', color: 'var(--text-secondary)' }}>Equity Curve</div>
                <div ref={chartContainerRef} style={{ width: '100%', height: '250px' }}></div>
              </div>
            </div>
          )}

        </div>

        {/* Footer */}
        <div style={{ padding: '16px 24px', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end', gap: '12px', backgroundColor: 'var(--bg-header)' }}>
          {result && (
            <>
              <button className="btn btn-ghost" onClick={() => setResult(null)}>New Backtest</button>
              <button className="btn btn-primary" onClick={() => onResult(result)} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Activity size={16} /> View Detailed Results
              </button>
            </>
          )}
          {!loading && !result && <button className="btn btn-primary" onClick={handleRun} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><Play size={16} /> Start Backtest</button>}
        </div>

      </div>
    </div>
  );
}
