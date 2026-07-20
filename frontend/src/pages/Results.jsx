import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChart, AreaSeries, HistogramSeries } from 'lightweight-charts';
import { ArrowLeft, TrendingUp, TrendingDown, Target, BarChart3, Activity, Award, Clock, Zap } from 'lucide-react';

export default function Results({ resultsData }) {
  const navigate = useNavigate();
  const equityChartRef = useRef(null);
  const equityChartInstance = useRef(null);
  const dailyChartRef = useRef(null);
  const dailyChartInstance = useRef(null);
  const [activeTradeTab, setActiveTradeTab] = useState('all');

  // Map from backend schema (BacktestResultModel) with fallback dummy data
  const results = resultsData || null;

  // ── Equity Curve Chart ────────────────────────────────
  useEffect(() => {
    if (!equityChartRef.current || !results?.equity_curve?.length) return;
    equityChartRef.current.innerHTML = '';

    const chart = createChart(equityChartRef.current, {
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#8b949e',
        fontFamily: "'Inter', sans-serif",
      },
      grid: {
        vertLines: { color: 'rgba(48, 54, 61, 0.3)' },
        horzLines: { color: 'rgba(48, 54, 61, 0.3)' },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
      crosshair: {
        mode: 1,
        vertLine: { color: 'rgba(201, 168, 76, 0.4)', labelBackgroundColor: '#21262d' },
        horzLine: { color: 'rgba(201, 168, 76, 0.4)', labelBackgroundColor: '#21262d' },
      },
      width: equityChartRef.current.clientWidth,
      height: equityChartRef.current.clientHeight,
    });

    const isProfit = results.total_pnl >= 0;
    const lineColor = isProfit ? '#3fb950' : '#f85149';

    const lineSeries = chart.addSeries(AreaSeries, {
      lineColor,
      topColor: isProfit ? 'rgba(63, 185, 80, 0.25)' : 'rgba(248, 81, 73, 0.25)',
      bottomColor: isProfit ? 'rgba(63, 185, 80, 0.0)' : 'rgba(248, 81, 73, 0.0)',
      lineWidth: 2,
    });

    const chartData = results.equity_curve
      .map(pt => ({
        time: Math.floor(new Date(pt.timestamp).getTime() / 1000),
        value: pt.value,
      }))
      .filter(d => !isNaN(d.time) && !isNaN(d.value))
      .sort((a, b) => a.time - b.time);

    if (chartData.length > 0) {
      lineSeries.setData(chartData);
      chart.timeScale().fitContent();
    }

    equityChartInstance.current = chart;

    const handleResize = () => {
      if (equityChartRef.current && equityChartInstance.current) {
        equityChartInstance.current.applyOptions({
          width: equityChartRef.current.clientWidth,
          height: equityChartRef.current.clientHeight,
        });
      }
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      equityChartInstance.current?.remove();
    };
  }, [results]);

  // ── Daily P&L Chart ────────────────────────────────
  useEffect(() => {
    if (!dailyChartRef.current || !results?.daily_stats?.length) return;
    dailyChartRef.current.innerHTML = '';

    const chart = createChart(dailyChartRef.current, {
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#8b949e',
        fontFamily: "'Inter', sans-serif",
      },
      grid: {
        vertLines: { color: 'rgba(48, 54, 61, 0.3)' },
        horzLines: { color: 'rgba(48, 54, 61, 0.3)' },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      width: dailyChartRef.current.clientWidth,
      height: dailyChartRef.current.clientHeight,
    });

    const histogramSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    });

    const histData = results.daily_stats
      .map(d => ({
        time: d.date,
        value: d.pnl,
        color: d.pnl >= 0 ? 'rgba(63, 185, 80, 0.7)' : 'rgba(248, 81, 73, 0.7)',
      }))
      .filter(d => !isNaN(d.value))
      .sort((a, b) => a.time.localeCompare(b.time));

    if (histData.length > 0) {
      histogramSeries.setData(histData);
      chart.timeScale().fitContent();
    }

    dailyChartInstance.current = chart;

    const handleResize = () => {
      if (dailyChartRef.current && dailyChartInstance.current) {
        dailyChartInstance.current.applyOptions({
          width: dailyChartRef.current.clientWidth,
          height: dailyChartRef.current.clientHeight,
        });
      }
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      dailyChartInstance.current?.remove();
    };
  }, [results]);

  // ── Empty State ────────────────────────────────
  if (!results) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '20px', padding: '60px' }}>
        <div style={{ fontSize: '64px', opacity: 0.3 }}>📊</div>
        <h2 style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '22px' }}>No Backtest Results</h2>
        <p style={{ color: 'var(--text-tertiary)', maxWidth: '400px', textAlign: 'center', lineHeight: 1.6 }}>
          Run a backtest from the Terminal page to see performance metrics, equity curves, and trade logs here.
        </p>
        <button className="btn btn-primary" onClick={() => navigate('/')}>
          Go to Terminal
        </button>
      </div>
    );
  }

  // ── Helper ────────────────────────────────
  const fmt = (n, d = 2) => {
    if (n == null || isNaN(n)) return '—';
    return Number(n).toFixed(d);
  };
  const fmtCurrency = (n) => {
    if (n == null || isNaN(n)) return '—';
    return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  };

  const trades = results.trades || [];
  const filteredTrades = activeTradeTab === 'all' ? trades
    : activeTradeTab === 'winners' ? trades.filter(t => t.pnl > 0)
    : trades.filter(t => t.pnl <= 0);

  return (
    <>
      <header className="header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button className="btn btn-sm btn-ghost" onClick={() => navigate('/')} style={{ padding: '4px 8px' }}>
            <ArrowLeft size={16} />
          </button>
          <h2 className="header-title">
            📊 Results: <span style={{ color: 'var(--accent-gold)' }}>{results.strategy_name}</span>
          </h2>
        </div>
        <div className="header-actions">
          <span className="badge badge-blue">{results.underlying}</span>
          <span className="badge badge-gold">{results.start_date} → {results.end_date}</span>
        </div>
      </header>

      <div className="page-container" style={{ paddingBottom: '40px' }}>

        {/* ── KPI Cards ────────────────────────────── */}
        <div className="results-kpi-grid">
          <div className={`stat-card ${results.total_pnl >= 0 ? 'green' : 'red'}`}>
            <div className="stat-icon">{results.total_pnl >= 0 ? <TrendingUp size={20} /> : <TrendingDown size={20} />}</div>
            <div className="stat-label">Total P&L</div>
            <div className="stat-value">{fmtCurrency(results.total_pnl)}</div>
            <div className={`stat-change ${results.total_pnl_pct >= 0 ? 'positive' : 'negative'}`}>
              {results.total_pnl_pct >= 0 ? '+' : ''}{fmt(results.total_pnl_pct)}%
            </div>
          </div>
          <div className={`stat-card ${results.win_rate >= 50 ? 'green' : 'red'}`}>
            <div className="stat-icon"><Target size={20} /></div>
            <div className="stat-label">Win Rate</div>
            <div className="stat-value">{fmt(results.win_rate, 1)}%</div>
            <div className="stat-change">{results.winning_trades}W / {results.losing_trades}L</div>
          </div>
          <div className={`stat-card ${results.profit_factor >= 1.5 ? 'green' : results.profit_factor >= 1 ? 'gold' : 'red'}`}>
            <div className="stat-icon"><Zap size={20} /></div>
            <div className="stat-label">Profit Factor</div>
            <div className="stat-value">{fmt(results.profit_factor)}</div>
            <div className="stat-change">Avg Win/Loss ratio</div>
          </div>
          <div className="stat-card red">
            <div className="stat-icon"><Activity size={20} /></div>
            <div className="stat-label">Max Drawdown</div>
            <div className="stat-value">{fmt(results.max_drawdown_pct)}%</div>
            <div className="stat-change">{fmtCurrency(results.max_drawdown)}</div>
          </div>
          <div className={`stat-card ${results.sharpe_ratio >= 1 ? 'green' : 'gold'}`}>
            <div className="stat-icon"><Award size={20} /></div>
            <div className="stat-label">Sharpe Ratio</div>
            <div className="stat-value">{fmt(results.sharpe_ratio)}</div>
            <div className="stat-change">Risk-adj return</div>
          </div>
          <div className="stat-card neutral">
            <div className="stat-icon"><BarChart3 size={20} /></div>
            <div className="stat-label">Total Trades</div>
            <div className="stat-value">{results.total_trades}</div>
            <div className="stat-change">
              <Clock size={12} style={{ display: 'inline', verticalAlign: 'middle' }} /> {fmt(results.avg_trade_duration, 0)} min avg
            </div>
          </div>
        </div>

        {/* ── Charts Row ────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px', marginBottom: '16px' }}>
          {/* Equity Curve */}
          <div className="card">
            <div className="card-header">
              <h3 className="card-title">📈 Equity Curve</h3>
              <div style={{ display: 'flex', gap: '12px', fontSize: '12px' }}>
                <span style={{ color: 'var(--text-tertiary)' }}>Initial: {fmtCurrency(results.initial_capital)}</span>
                <span style={{ color: results.final_capital >= results.initial_capital ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                  Final: {fmtCurrency(results.final_capital)}
                </span>
              </div>
            </div>
            <div ref={equityChartRef} style={{ width: '100%', height: '320px' }} />
          </div>

          {/* Performance Breakdown */}
          <div className="card">
            <div className="card-header">
              <h3 className="card-title">📋 Performance</h3>
            </div>
            <div style={{ padding: '0 16px 16px' }}>
              {[
                ['Sortino Ratio', fmt(results.sortino_ratio)],
                ['Calmar Ratio', fmt(results.calmar_ratio)],
                ['Avg Profit', fmtCurrency(results.avg_profit)],
                ['Avg Loss', fmtCurrency(results.avg_loss)],
                ['Max Consec Wins', results.max_consecutive_wins],
                ['Max Consec Losses', results.max_consecutive_losses],
                ['Avg Duration', `${fmt(results.avg_trade_duration, 0)} min`],
              ].map(([label, value], i) => (
                <div key={i} style={{
                  display: 'flex', justifyContent: 'space-between', padding: '10px 0',
                  borderBottom: i < 6 ? '1px solid var(--border-subtle)' : 'none',
                  fontSize: '13px',
                }}>
                  <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-primary)' }}>{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Daily P&L Chart ────────────────────────────── */}
        <div className="card" style={{ marginBottom: '16px' }}>
          <div className="card-header">
            <h3 className="card-title">📊 Daily P&L</h3>
            <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
              {results.daily_stats?.length || 0} trading days
            </span>
          </div>
          <div ref={dailyChartRef} style={{ width: '100%', height: '200px' }} />
        </div>

        {/* ── Trade Log ────────────────────────────── */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">📝 Trade Log</h3>
            <div style={{ display: 'flex', gap: '4px' }}>
              {['all', 'winners', 'losers'].map(tab => (
                <button
                  key={tab}
                  className={`btn btn-sm ${activeTradeTab === tab ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setActiveTradeTab(tab)}
                >
                  {tab === 'all' ? `All (${trades.length})` :
                   tab === 'winners' ? `Winners (${trades.filter(t => t.pnl > 0).length})` :
                   `Losers (${trades.filter(t => t.pnl <= 0).length})`}
                </button>
              ))}
            </div>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table className="results-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Side</th>
                  <th>Type</th>
                  <th>Strike</th>
                  <th>Expiry</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Entry Time</th>
                  <th>Exit Time</th>
                  <th>P&L</th>
                  <th>P&L %</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {filteredTrades.length === 0 ? (
                  <tr><td colSpan={13} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-tertiary)' }}>No trades</td></tr>
                ) : (
                  filteredTrades.map((t, i) => (
                    <tr key={t.id || i}>
                      <td style={{ color: 'var(--text-tertiary)' }}>{i + 1}</td>
                      <td>
                        <span className={`badge ${t.side === 'BUY' ? 'badge-green' : 'badge-red'}`} style={{ fontSize: '10px' }}>
                          {t.side}
                        </span>
                      </td>
                      <td>{t.option_type}</td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>{t.strike}</td>
                      <td>{t.expiry}</td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>{t.quantity}</td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>₹{fmt(t.entry_price)}</td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>₹{fmt(t.exit_price)}</td>
                      <td style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>{t.entry_time?.split('T')[1]?.slice(0, 8) || t.entry_time}</td>
                      <td style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>{t.exit_time?.split('T')[1]?.slice(0, 8) || t.exit_time}</td>
                      <td style={{
                        fontFamily: 'var(--font-mono)', fontWeight: 600,
                        color: t.pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)',
                      }}>
                        {t.pnl >= 0 ? '+' : ''}{fmtCurrency(t.pnl)}
                      </td>
                      <td style={{
                        fontFamily: 'var(--font-mono)',
                        color: t.pnl_pct >= 0 ? 'var(--accent-green)' : 'var(--accent-red)',
                      }}>
                        {t.pnl_pct >= 0 ? '+' : ''}{fmt(t.pnl_pct)}%
                      </td>
                      <td style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>{t.exit_reason || '—'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </>
  );
}
