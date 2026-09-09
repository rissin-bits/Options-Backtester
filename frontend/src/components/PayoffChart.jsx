import React, { useMemo, useState } from 'react';

export default function PayoffChart({ strategyPositions, underlyingPrice, lotSize = 1 }) {
  const [hoverPrice, setHoverPrice] = useState(null);

  // strategyPositions: Array of { strike, type: 'CE'|'PE', side: 'BUY'|'SELL', premium, qty }
  
  const { minStrike, maxStrike } = useMemo(() => {
    const spot = Number(underlyingPrice) > 0 ? Number(underlyingPrice) : 0;
    if (!strategyPositions || strategyPositions.length === 0) {
      return { minStrike: spot * 0.9, maxStrike: spot * 1.1 };
    }
    // Only fold spot into the range when it's a real price. A zero/stale spot
    // used to drag the x-axis down to 0 and squash the payoff into a spike.
    const values = strategyPositions.map(p => Number(p.strike)).filter(Number.isFinite);
    if (spot > 0) values.push(spot);
    if (!values.length) return { minStrike: 0, maxStrike: 1 };

    let minS = Math.min(...values);
    let maxS = Math.max(...values);

    // Guarantee a span wide enough to actually show the payoff profile.
    // A straddle puts every leg on one strike, so the raw span is just the
    // gap between spot and that strike — a few points wide, which rendered
    // as a vertical spike with both breakevens off-screen.
    const center = spot > 0 ? spot : (minS + maxS) / 2;
    const minSpan = Math.abs(center) * 0.10 || 1;   // ±5% of spot
    if (maxS - minS < minSpan) {
      const mid = (minS + maxS) / 2;
      minS = mid - minSpan / 2;
      maxS = mid + minSpan / 2;
    }
    return { minStrike: minS, maxStrike: maxS };
  }, [strategyPositions, underlyingPrice]);

  const range = (maxStrike - minStrike) || Math.max(1, maxStrike * 0.1);
  const startPrice = Math.max(0, minStrike - range * 0.4);
  const endPrice = maxStrike + range * 0.4;
  
  const steps = 150;
  const stepSize = (endPrice - startPrice) / steps;
  
  const data = useMemo(() => {
    if (!strategyPositions || strategyPositions.length === 0) return [];
    
    let points = [];
    for (let i = 0; i <= steps; i++) {
      const price = startPrice + i * stepSize;
      let pnl = 0;
      
      strategyPositions.forEach(pos => {
        let intrinsicValue = 0;
        if (pos.type === 'CE') {
          intrinsicValue = Math.max(0, price - pos.strike);
        } else {
          intrinsicValue = Math.max(0, pos.strike - price);
        }
        
        let positionPnl = 0;
        if (pos.side === 'BUY') {
          positionPnl = (intrinsicValue - pos.premium) * (pos.qty || 1) * lotSize;
        } else {
          positionPnl = (pos.premium - intrinsicValue) * (pos.qty || 1) * lotSize;
        }
        
        pnl += positionPnl;
      });
      points.push({ price, pnl });
    }
    return points;
  }, [strategyPositions, startPrice, stepSize, steps]);
  
  if (data.length === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-tertiary)', fontSize: '13px' }}>
        Add legs to visualize payoff
      </div>
    );
  }

  const minPnl = Math.min(...data.map(d => d.pnl));
  const maxPnl = Math.max(...data.map(d => d.pnl));
  // A flat payoff (every point equal) gives a zero range -> division by zero
  // in getY, which renders NaN path coordinates and a blank chart.
  const pnlRange = (maxPnl - minPnl) || Math.max(1, Math.abs(maxPnl) * 0.2 || 1);

  // Add some padding to Y axis so lines don't hit the absolute edges
  const yPadding = pnlRange * 0.1;
  const chartMinPnl = minPnl - yPadding;
  const chartMaxPnl = maxPnl + yPadding;
  const chartPnlRange = (chartMaxPnl - chartMinPnl) || 1;

  // Viewport dimensions (SVG viewbox)
  const width = 800;
  const height = 400;
  const padding = { top: 28, right: 48, bottom: 40, left: 68 };
  
  const getX = (price) => padding.left + ((price - startPrice) / (endPrice - startPrice)) * (width - padding.left - padding.right);
  const getY = (pnl) => height - padding.bottom - ((pnl - chartMinPnl) / chartPnlRange) * (height - padding.top - padding.bottom);
  
  const zeroY = getY(0);
  
  // Split data into profit and loss segments for shading
  const profitPoints = data.map(d => ({ x: getX(d.price), y: Math.min(getY(d.pnl), zeroY) }));
  const lossPoints = data.map(d => ({ x: getX(d.price), y: Math.max(getY(d.pnl), zeroY) }));

  const profitPath = profitPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ` L ${getX(endPrice)} ${zeroY} L ${getX(startPrice)} ${zeroY} Z`;
  const lossPath = lossPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ` L ${getX(endPrice)} ${zeroY} L ${getX(startPrice)} ${zeroY} Z`;
  
  const linePath = data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(d.price)} ${getY(d.pnl)}`).join(' ');

  // Ticks
  const priceTicks = [];
  for (let i = 0; i <= 5; i++) {
    priceTicks.push(startPrice + (i / 5) * (endPrice - startPrice));
  }

  const handleMouseMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    // Map x to SVG coordinates
    const svgX = (x / rect.width) * width;
    if (svgX >= padding.left && svgX <= width - padding.right) {
      const ratio = (svgX - padding.left) / (width - padding.left - padding.right);
      const price = startPrice + ratio * (endPrice - startPrice);
      
      // Find closest data point
      const point = data.reduce((prev, curr) => Math.abs(curr.price - price) < Math.abs(prev.price - price) ? curr : prev);
      setHoverPrice(point);
    } else {
      setHoverPrice(null);
    }
  };

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <svg 
        width="100%" 
        height="100%" 
        viewBox={`0 0 ${width} ${height}`}
        /* "none" stretched the 800x400 viewBox to fill a ~250x150 panel,
           distorting the payoff line and squashing every label. Preserve the
           aspect ratio and let the SVG letterbox instead. */
        preserveAspectRatio="xMidYMid meet"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverPrice(null)}
        style={{ display: 'block', cursor: 'crosshair' }}
      >
        {/* Zero Line */}
        <line x1={padding.left} y1={zeroY} x2={width - padding.right} y2={zeroY} stroke="var(--border-color)" strokeWidth="1.5" />
        
        {/* Current Underlying Price Line */}
        {underlyingPrice >= startPrice && underlyingPrice <= endPrice && (
          <g>
            <line 
              x1={getX(underlyingPrice)} 
              y1={padding.top} 
              x2={getX(underlyingPrice)} 
              y2={height - padding.bottom} 
              stroke="var(--accent-yellow)" 
              strokeWidth="1" 
              strokeDasharray="4 4" 
            />
            <text x={getX(underlyingPrice)} y={padding.top - 8} fill="var(--accent-yellow)" fontSize="13" textAnchor="middle" fontFamily="var(--font-mono)">
              Spot {Number(underlyingPrice).toFixed(2)}
            </text>
          </g>
        )}
        
        {/* Profit/Loss Shading */}
        <path d={profitPath} fill="rgba(63, 185, 80, 0.15)" />
        <path d={lossPath} fill="rgba(248, 81, 73, 0.15)" />
        
        {/* Main Payoff Line */}
        <path d={linePath} fill="none" stroke="var(--accent-blue)" strokeWidth="2.5" />
        
        {/* X-axis Ticks */}
        {priceTicks.map(t => (
          <g key={t}>
            <line x1={getX(t)} y1={height - padding.bottom} x2={getX(t)} y2={height - padding.bottom + 5} stroke="var(--border-color)" strokeWidth="1" />
            <text x={getX(t)} y={height - padding.bottom + 20} fill="var(--text-tertiary)" fontSize="12" textAnchor="middle" fontFamily="var(--font-mono)">
              {t.toFixed(0)}
            </text>
          </g>
        ))}

        {/* Y-axis labels */}
        <text x={padding.left - 10} y={getY(maxPnl)} fill="var(--accent-green)" fontSize="12" textAnchor="end" dominantBaseline="middle" fontFamily="var(--font-mono)">
          +{maxPnl.toFixed(0)}
        </text>
        <text x={padding.left - 10} y={getY(minPnl)} fill="var(--accent-red)" fontSize="12" textAnchor="end" dominantBaseline="middle" fontFamily="var(--font-mono)">
          {minPnl.toFixed(0)}
        </text>
        <text x={padding.left - 10} y={zeroY} fill="var(--text-tertiary)" fontSize="12" textAnchor="end" dominantBaseline="middle" fontFamily="var(--font-mono)">
          0
        </text>

        {/* Hover Crosshair */}
        {hoverPrice && (
          <g>
            <line 
              x1={getX(hoverPrice.price)} y1={padding.top} 
              x2={getX(hoverPrice.price)} y2={height - padding.bottom} 
              stroke="var(--text-secondary)" strokeWidth="1" strokeDasharray="2 2" 
            />
            <circle cx={getX(hoverPrice.price)} cy={getY(hoverPrice.pnl)} r="4" fill="var(--accent-blue)" />
            
            {/* Tooltip Box */}
            <rect 
              x={getX(hoverPrice.price) > width / 2 ? getX(hoverPrice.price) - 130 : getX(hoverPrice.price) + 10} 
              y={getY(hoverPrice.pnl) - 40} 
              width="120" 
              height="50" 
              rx="4" 
              fill="var(--bg-tertiary)" 
              stroke="var(--border-color)"
            />
            <text 
              x={getX(hoverPrice.price) > width / 2 ? getX(hoverPrice.price) - 120 : getX(hoverPrice.price) + 20} 
              y={getY(hoverPrice.pnl) - 20} 
              fill="var(--text-primary)" 
              fontSize="12" 
              fontFamily="var(--font-mono)"
            >
              Spot: {hoverPrice.price.toFixed(1)}
            </text>
            <text 
              x={getX(hoverPrice.price) > width / 2 ? getX(hoverPrice.price) - 120 : getX(hoverPrice.price) + 20} 
              y={getY(hoverPrice.pnl) - 5} 
              fill={hoverPrice.pnl >= 0 ? "var(--accent-green-light)" : "var(--accent-red-light)"} 
              fontSize="12" 
              fontFamily="var(--font-mono)"
              fontWeight="bold"
            >
              P&L: {hoverPrice.pnl >= 0 ? '+' : ''}{hoverPrice.pnl.toFixed(1)}
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}
