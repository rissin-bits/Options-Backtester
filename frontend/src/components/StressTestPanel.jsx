import React, { useState } from 'react';
import { API_BASE } from '../App';

export default function StressTestPanel({ legs, spotPrice, iv = 15.0, dte = 7, lotSize = 1 }) {
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const runAnalysis = async () => {
    if (!legs || legs.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const payload = {
        spot_price: spotPrice,
        current_iv: iv / 100, // Convert to decimal for backend
        days_to_expiry: dte,
        legs: legs,
        lot_size: lotSize
      };

      const res = await fetch(`${API_BASE}/api/analysis/stress-test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (!res.ok) throw new Error("Failed to run stress test");
      const data = await res.json();
      setResults(data.scenarios);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-col gap-2">
      <div className="flex justify-between items-center" style={{ marginBottom: '8px' }}>
        <span className="text-muted" style={{ fontSize: '12px' }}>Scenario Analysis</span>
        <button className="btn btn-sm" onClick={runAnalysis} disabled={loading || !legs?.length}>
          {loading ? 'Running...' : 'Run Stress Test'}
        </button>
      </div>

      {error && <div className="text-red" style={{ fontSize: '12px' }}>{error}</div>}

      {results && results.length > 0 && (
        <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ textAlign: 'left' }}>Scenario</th>
                <th>Spot %</th>
                <th>IV %</th>
                <th>Est. P&L</th>
              </tr>
            </thead>
            <tbody>
              {results.map((s, i) => (
                <tr key={i}>
                  <td style={{ textAlign: 'left', color: 'var(--text-secondary)' }}>{s.name}</td>
                  <td>{(s.spot_shock * 100).toFixed(1)}%</td>
                  <td>{(s.iv_shock * 100).toFixed(1)}%</td>
                  <td className={s.result.pnl >= 0 ? 'text-green' : 'text-red'} style={{ fontWeight: 'bold' }}>
                    {s.result.pnl >= 0 ? '+' : ''}{s.result.pnl.toFixed(0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!results && !loading && legs?.length > 0 && (
        <div className="text-center text-muted" style={{ padding: '16px', fontSize: '12px' }}>
          Run stress test to see hypothetical P&L scenarios.
        </div>
      )}
    </div>
  );
}
