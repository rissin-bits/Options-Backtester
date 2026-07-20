import React from 'react';

export default function GreeksPanel({ legs, lotSize = 1 }) {
  if (!legs || legs.length === 0) {
    return (
      <div className="text-center text-muted" style={{ padding: '20px', fontSize: '13px' }}>
        No positions to display Greeks
      </div>
    );
  }

  // Calculate portfolio totals
  let totalDelta = 0;
  let totalGamma = 0;
  let totalTheta = 0;
  let totalVega = 0;

  legs.forEach(leg => {
    const mult = leg.side === 'BUY' ? 1 : -1;
    const qty = leg.qty || 1;
    totalDelta += (leg.delta || 0) * mult * qty * lotSize;
    totalGamma += (leg.gamma || 0) * mult * qty * lotSize;
    totalTheta += (leg.theta || 0) * mult * qty * lotSize;
    totalVega += (leg.vega || 0) * mult * qty * lotSize;
  });

  const GreeksRow = ({ label, value, decimals = 2, invertColors = false }) => {
    const isPositive = value >= 0;
    const isNeutral = Math.abs(value) < 0.001;
    
    let colorClass = 'text-muted';
    if (!isNeutral) {
      if (invertColors) {
        colorClass = isPositive ? 'text-red' : 'text-green';
      } else {
        colorClass = isPositive ? 'text-green' : 'text-red';
      }
    }

    return (
      <div className="form-group inline justify-between" style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-color)' }}>
        <span className="text-muted font-mono" style={{ fontSize: '12px' }}>{label}</span>
        <span className={`font-mono font-bold ${colorClass}`} style={{ fontSize: '13px' }}>
          {value > 0 ? '+' : ''}{value.toFixed(decimals)}
        </span>
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <GreeksRow label="Net Delta" value={totalDelta} />
      <GreeksRow label="Net Gamma" value={totalGamma} decimals={4} />
      <GreeksRow label="Net Theta" value={totalTheta} invertColors={false} />
      <GreeksRow label="Net Vega" value={totalVega} />
    </div>
  );
}
