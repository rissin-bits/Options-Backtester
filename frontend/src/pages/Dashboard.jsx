import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { API_BASE } from '../App';

const EXAMPLE_STRATEGIES = [
  {
    name: '9:20 Short Straddle',
    description: 'Sell ATM CE + PE at 9:20 AM, exit at 3:15 PM. Classic intraday theta decay.',
    icon: '🎯',
    type: 'Intraday',
    risk: 'High',
  },
  {
    name: 'Expiry Day Straddle',
    description: 'Thursday-only short straddle with tight stop loss. Exploits weekly expiry theta crush.',
    icon: '📅',
    type: 'Expiry',
    risk: 'High',
  },
  {
    name: 'Iron Condor',
    description: 'Sell OTM CE + PE with defined risk protection. Range-bound market strategy.',
    icon: '🦅',
    type: 'Positional',
    risk: 'Medium',
  },
  {
    name: 'RSI Mean Reversion',
    description: 'Buy when RSI < 30 (oversold), exit when RSI > 70 (overbought). Contrarian.',
    icon: '📉',
    type: 'Indicator',
    risk: 'Medium',
  },
  {
    name: 'VWAP Breakout',
    description: 'Buy CE/PE based on VWAP crossover direction. Momentum-based intraday.',
    icon: '📊',
    type: 'Momentum',
    risk: 'Medium',
  },
];

export default function Dashboard() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetch(`${API_BASE}/api/status`)
      .then(r => r.json())
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <header className="header">
        <h2 className="header-title">📊 Dashboard</h2>
        <div className="header-actions">
          <span className={`badge ${status ? 'badge-green' : 'badge-red'}`}>
            {status ? '● Engine Online' : '○ Engine Offline'}
          </span>
        </div>
      </header>

      <div className="page-container">
        {/* Welcome banner */}
        <div className="card" style={{
          background: 'linear-gradient(135deg, rgba(201, 168, 76, 0.08), rgba(74, 124, 255, 0.05))',
          borderColor: 'rgba(201, 168, 76, 0.2)',
          marginBottom: '24px',
          position: 'relative',
          overflow: 'hidden'
        }}>
          <div style={{
            position: 'absolute',
            right: '-40px',
            top: '-20px',
            fontSize: '120px',
            opacity: 0.05,
          }}>📈</div>
          <h2 style={{
            fontFamily: 'var(--font-display)',
            fontSize: '28px',
            fontWeight: 800,
            marginBottom: '8px',
            background: 'linear-gradient(135deg, var(--accent-gold), var(--accent-gold-light))',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>
            Options Backtester
          </h2>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '600px', marginBottom: '16px' }}>
            Build, test, and optimize options trading strategies with historical
            NIFTY & BANKNIFTY data. Support for time-based, price-based, and
            indicator-based entry/exit conditions.
          </p>
          <div style={{ display: 'flex', gap: '12px' }}>
            <button className="btn btn-primary" onClick={() => navigate('/')}>
              🎯 Build Strategy
            </button>
            <button className="btn btn-secondary" onClick={() => navigate('/code')}>
              💻 Write Code
            </button>
          </div>
        </div>

        {/* Quick Stats */}
        <div className="stats-grid">
          <div className="stat-card gold">
            <div className="stat-label">Engine Status</div>
            <div className="stat-value" style={{ fontSize: '18px' }}>
              {loading ? (
                <span className="skeleton" style={{ display: 'inline-block', width: 80, height: 24 }}>&nbsp;</span>
              ) : status ? '✅ Running' : '⏸️ Offline'}
            </div>
            <div className="stat-change" style={{ color: 'var(--text-tertiary)' }}>
              FastAPI + Python Engine
            </div>
          </div>

          <div className="stat-card neutral">
            <div className="stat-label">Underlyings</div>
            <div className="stat-value">
              {status?.underlyings?.length ?? '—'}
            </div>
            <div className="stat-change" style={{ color: 'var(--text-tertiary)' }}>
              {status?.underlyings?.join(', ') ?? 'No data loaded'}
            </div>
          </div>

          <div className="stat-card neutral">
            <div className="stat-label">Data Available</div>
            <div className="stat-value" style={{ fontSize: '18px' }}>
              {status?.data_available ? '✅ Yes' : '⚠️ Pending'}
            </div>
            <div className="stat-change" style={{ color: 'var(--text-tertiary)' }}>
              1-min OHLCV + Daily
            </div>
          </div>

          <div className="stat-card gold">
            <div className="stat-label">Strategies</div>
            <div className="stat-value">{EXAMPLE_STRATEGIES.length}</div>
            <div className="stat-change" style={{ color: 'var(--text-tertiary)' }}>
              Built-in templates
            </div>
          </div>
        </div>

        {/* Example Strategies */}
        <div className="card" style={{ marginBottom: '24px' }}>
          <div className="card-header">
            <div>
              <h3 className="card-title">📋 Strategy Templates</h3>
              <p className="card-subtitle">Quick-start with proven options strategies</p>
            </div>
            <button className="btn btn-sm btn-ghost" onClick={() => navigate('/')}>
              View All →
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
            {EXAMPLE_STRATEGIES.map((s, i) => (
              <div
                key={i}
                className="condition-block"
                style={{ cursor: 'pointer' }}
                onClick={() => navigate('/')}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                  <span style={{ fontSize: '24px' }}>{s.icon}</span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '14px' }}>{s.name}</div>
                    <div style={{ display: 'flex', gap: '6px', marginTop: '4px' }}>
                      <span className="badge badge-blue">{s.type}</span>
                      <span className={`badge ${s.risk === 'High' ? 'badge-red' : 'badge-gold'}`}>
                        {s.risk} Risk
                      </span>
                    </div>
                  </div>
                </div>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  {s.description}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Features Grid */}
        <div className="grid-3" style={{ marginBottom: '24px' }}>
          <div className="card" style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>⏰</div>
            <h4 style={{ marginBottom: '8px', color: 'var(--accent-gold)' }}>Time-Based</h4>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Enter at 9:20, exit at 15:15. Day-of-week filters, expiry day logic.
            </p>
          </div>
          <div className="card" style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>💰</div>
            <h4 style={{ marginBottom: '8px', color: 'var(--accent-gold)' }}>Price-Based</h4>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Spot price levels, stop loss %, profit targets, premium thresholds.
            </p>
          </div>
          <div className="card" style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>📐</div>
            <h4 style={{ marginBottom: '8px', color: 'var(--accent-gold)' }}>Indicator-Based</h4>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              RSI, MACD, VWAP, Bollinger, SuperTrend, ATR and 15+ more indicators.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
