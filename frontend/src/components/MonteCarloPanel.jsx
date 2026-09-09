import React, { useState, useEffect, useRef } from 'react';
import { API_BASE } from '../App';
import { createChart, HistogramSeries } from 'lightweight-charts';

export default function MonteCarloPanel({ legs, spotPrice, iv = 15.0, dte = 7, lotSize = 1 }) {
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const chartContainerRef = useRef(null);
  const chartInstance = useRef(null);

  const runAnalysis = async () => {
    if (!legs || legs.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const payload = {
        spot_price: spotPrice,
        current_iv: iv / 100, // Convert to decimal
        days_to_expiry: dte,
        legs: legs,
        lot_size: lotSize
      };

      const res = await fetch(`${API_BASE}/api/analysis/monte-carlo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (!res.ok) throw new Error("Failed to run monte carlo");
      const data = await res.json();
      setResults(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (results && results.histogram && chartContainerRef.current) {
      chartContainerRef.current.innerHTML = '';
      
      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: 'solid', color: 'transparent' },
          textColor: '#8b949e',
        },
        grid: {
          vertLines: { visible: false },
          horzLines: { color: 'rgba(48, 54, 61, 0.5)' },
        },
        timeScale: { visible: false },
        rightPriceScale: { borderVisible: false },
        width: chartContainerRef.current.clientWidth || 300,
        height: 120,
      });

      const histogramSeries = chart.addSeries(HistogramSeries, {
        color: '#58a6ff',
      });
      
      // Map bins to a pseudo-time axis for lightweight-charts
      const data = results.histogram.map((bin, i) => ({
        time: i,
        value: bin.count,
        color: bin.bin_start >= 0 ? 'rgba(63, 185, 80, 0.6)' : 'rgba(248, 81, 73, 0.6)'
      }));

      histogramSeries.setData(data);
      chart.timeScale().fitContent();
      chartInstance.current = chart;

      return () => {
        if (chartInstance.current) {
          chartInstance.current.remove();
        }
      };
    }
  }, [results]);

  return (
    <div className="flex-col gap-2">
      <div className="flex justify-between items-center" style={{ marginBottom: '8px' }}>
        <span className="text-muted" style={{ fontSize: '12px' }}>Monte Carlo (1000 paths)</span>
        <button className="btn btn-sm" onClick={runAnalysis} disabled={loading || !legs?.length}>
          {loading ? 'Running...' : 'Run Simulation'}
        </button>
      </div>

      {error && <div className="text-red" style={{ fontSize: '12px' }}>{error}</div>}

      {results && (
        <div className="flex-col gap-2">
          <div className="flex gap-4">
            <div style={{ flex: 1 }}>
              <div className="text-muted" style={{ fontSize: '11px' }}>Prob. of Profit</div>
              <div className="text-primary font-mono" style={{ fontSize: '14px', fontWeight: 'bold' }}>
                {results.prob_profit.toFixed(1)}%
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <div className="text-muted" style={{ fontSize: '11px' }}>Expected Value</div>
              <div className={results.expected_value >= 0 ? 'text-green font-mono' : 'text-red font-mono'} style={{ fontSize: '14px', fontWeight: 'bold' }}>
                {results.expected_value >= 0 ? '+' : ''}{results.expected_value.toFixed(0)}
              </div>
            </div>
          </div>
          
          <div className="text-muted" style={{ fontSize: '11px', marginTop: '4px' }}>P&L Distribution</div>
          <div ref={chartContainerRef} style={{ width: '100%', height: '120px' }}></div>
          
          <div className="flex justify-between text-muted" style={{ fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
            <span>90% CI: {results.confidence_interval_90[0].toFixed(0)} to {results.confidence_interval_90[1].toFixed(0)}</span>
          </div>
        </div>
      )}
      
      {!results && !loading && legs?.length > 0 && (
        <div className="text-center text-muted" style={{ padding: '16px', fontSize: '12px' }}>
          Run Monte Carlo to simulate probability of profit and expected returns.
        </div>
      )}
    </div>
  );
}
