import React, { useState, useMemo, useEffect } from 'react';
import PayoffChart from '../components/PayoffChart';
import GreeksPanel from '../components/GreeksPanel';
import StressTestPanel from '../components/StressTestPanel';
import MonteCarloPanel from '../components/MonteCarloPanel';
import { Activity, LayoutList, Settings2, Plus, X } from 'lucide-react';

const STRATEGY_PRESETS = [
  { name: 'Short Straddle', legs: [{ side: 'SELL', type: 'CE', strike: 0 }, { side: 'SELL', type: 'PE', strike: 0 }] },
  { name: 'Iron Condor', legs: [
      { side: 'SELL', type: 'PE', strike: -2 }, { side: 'BUY', type: 'PE', strike: -4 },
      { side: 'SELL', type: 'CE', strike: 2 }, { side: 'BUY', type: 'CE', strike: 4 }
    ] },
  { name: 'Bull Call Spread', legs: [{ side: 'BUY', type: 'CE', strike: 0 }, { side: 'SELL', type: 'CE', strike: 2 }] },
  { name: 'Bear Put Spread', legs: [{ side: 'BUY', type: 'PE', strike: 0 }, { side: 'SELL', type: 'PE', strike: -2 }] },
];

// NSE contract lot sizes, used when the chain hasn't reported one yet.
const LOT_SIZES = { NIFTY: 25, BANKNIFTY: 15, FINNIFTY: 25, MIDCPNIFTY: 50, SENSEX: 10 };

export default function StrategyBuilder({ legs, setLegs, chain }) {
  // Everything below is sourced from the live options chain, with a manual
  // override kept for each so the panel still works before a chain has loaded.
  const [spotOverride, setSpotOverride] = useState(null);
  const [lotOverride, setLotOverride] = useState(null);
  const [dteOverride, setDteOverride] = useState(null);
  const [ivOverride, setIvOverride] = useState(null);

  const spotPrice = spotOverride ?? (chain?.spotPrice || 0);
  const lotSize = lotOverride ?? (LOT_SIZES[chain?.underlying] ?? 50);
  const dte = dteOverride ?? (chain?.dte ?? 7);

  const strikes = chain?.strikes ?? [];
  const strikeStep = chain?.step ?? 50;

  // Real premium/greeks for a given (strike, type) straight off the chain.
  const quoteFor = (strike, type) => chain?.quotes?.[`${strike}_${type}`] || null;

  // Snap an arbitrary price to the nearest strike that actually exists.
  const nearestStrike = (price) => {
    if (!strikes.length) return Math.round(price / strikeStep) * strikeStep;
    return strikes.reduce((best, s) =>
      Math.abs(s - price) < Math.abs(best - price) ? s : best, strikes[0]);
  };

  // Move `offset` strikes away from ATM, staying on the real strike ladder.
  const strikeAtOffset = (offset) => {
    const atm = nearestStrike(spotPrice);
    if (!strikes.length) return atm + offset * strikeStep;
    const i = strikes.indexOf(atm);
    return strikes[Math.max(0, Math.min(strikes.length - 1, i + offset))];
  };

  // Build a leg with live premium and greeks; fall back only if unquoted.
  const makeLeg = (side, type, strike) => {
    const q = quoteFor(strike, type);
    return {
      id: Math.random().toString(36).substr(2, 9),
      side, type, strike, qty: 1,
      premium: q?.close ?? 0,
      iv: q?.iv ?? 15.0,
      delta: q?.delta ?? (type === 'CE' ? 0.5 : -0.5),
      gamma: q?.gamma ?? 0.01,
      theta: q?.theta ?? -5,
      vega: q?.vega ?? 12,
      unquoted: !q,
    };
  };

  // Legs added from the options chain carry a real IV (in %). Average them so
  // the stress-test / Monte Carlo panels model the position actually on screen
  // instead of a flat 15% assumption. The user can still override.
  const impliedIv = useMemo(() => {
    const ivs = legs
      .map(l => Number(l.iv))
      .filter(v => Number.isFinite(v) && v > 0);
    if (!ivs.length) return 15.0;
    return ivs.reduce((a, b) => a + b, 0) / ivs.length;
  }, [legs]);

  const iv = ivOverride ?? impliedIv;

  const loadPreset = (preset) => {
    // preset offsets are in strikes-from-ATM, resolved against the real ladder.
    setLegs(preset.legs.map(l => makeLeg(l.side, l.type, strikeAtOffset(l.strike))));
  };

  const updateLeg = (id, field, value) => {
    setLegs(legs.map(l => {
      if (l.id !== id) return l;
      const next = { ...l, [field]: value };
      // Changing the contract must re-quote it, otherwise the premium and
      // greeks silently describe the option you were looking at before.
      if (field === 'strike' || field === 'type') {
        const q = quoteFor(next.strike, next.type);
        if (q) {
          next.premium = q.close ?? next.premium;
          next.iv = q.iv ?? next.iv;
          next.delta = q.delta ?? next.delta;
          next.gamma = q.gamma ?? next.gamma;
          next.theta = q.theta ?? next.theta;
          next.vega = q.vega ?? next.vega;
          next.unquoted = false;
        } else {
          next.unquoted = true;
        }
      }
      return next;
    }));
  };

  const removeLeg = (id) => {
    setLegs(legs.filter(l => l.id !== id));
  };

  const addCustomLeg = () => {
    setLegs([...legs, makeLeg('BUY', 'CE', nearestStrike(spotPrice))]);
  };

  // Re-price existing legs when the underlying, expiry or timestamp changes, so
  // the builder never shows quotes from a chain that is no longer on screen.
  const chainKey = `${chain?.underlying}_${chain?.expiry}_${chain?.spotPrice}`;
  useEffect(() => {
    if (!chain?.quotes || !legs.length) return;
    setLegs(prev => prev.map(l => {
      const q = chain.quotes[`${l.strike}_${l.type}`];
      if (!q) return { ...l, unquoted: true };
      return { ...l, premium: q.close ?? l.premium, iv: q.iv ?? l.iv,
               delta: q.delta ?? l.delta, gamma: q.gamma ?? l.gamma,
               theta: q.theta ?? l.theta, vega: q.vega ?? l.vega, unquoted: false };
    }));
  }, [chainKey]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      
      {/* Top: Strategy Legs */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderBottom: '1px solid var(--border-color)', minHeight: '40%' }}>
        <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'var(--bg-tertiary)', padding: '8px 16px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 600 }}>
            <LayoutList size={16} color="var(--accent-blue-light)" />
            Strategy Builder
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            {STRATEGY_PRESETS.map(p => (
              <button key={p.name} className="btn btn-sm btn-ghost" onClick={() => loadPreset(p)} style={{ fontSize: '11px', padding: '4px 8px' }}>
                {p.name}
              </button>
            ))}
            <button className="btn btn-sm btn-primary" onClick={addCustomLeg} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Plus size={14} /> Add Leg
            </button>
          </div>
        </div>
        
        <div style={{ overflow: 'auto', flex: 1 }}>
          {legs.length === 0 ? (
            <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--text-tertiary)', fontSize: '13px' }}>
              Select a preset or add a leg to build a strategy.
            </div>
          ) : (
            <table className="data-table" style={{ width: '100%', fontSize: '12px' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'center', width: '40px' }}></th>
                  <th style={{ textAlign: 'center' }}>B/S</th>
                  <th style={{ textAlign: 'center' }}>QTY</th>
                  <th style={{ textAlign: 'center' }}>TYPE</th>
                  <th style={{ textAlign: 'center' }}>STRIKE</th>
                  <th style={{ textAlign: 'center' }}>PREMIUM</th>
                  <th style={{ textAlign: 'center' }}>IV%</th>
                </tr>
              </thead>
              <tbody>
                {legs.map(leg => (
                  <tr key={leg.id}>
                    <td style={{ textAlign: 'center' }}>
                      <button className="btn btn-ghost" style={{ padding: '4px', color: 'var(--accent-red)' }} onClick={() => removeLeg(leg.id)}>
                        <X size={14} />
                      </button>
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <select style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: leg.side === 'BUY' ? 'var(--accent-green-light)' : 'var(--accent-red-light)', fontWeight: 600, padding: '4px', borderRadius: '4px', outline: 'none' }} value={leg.side} onChange={e => updateLeg(leg.id, 'side', e.target.value)}>
                        <option value="BUY">BUY</option>
                        <option value="SELL">SELL</option>
                      </select>
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <input type="number" style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px', borderRadius: '4px', width: '50px', textAlign: 'center', outline: 'none' }} value={leg.qty} onChange={e => updateLeg(leg.id, 'qty', parseInt(e.target.value) || 1)} min="1" />
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <select style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px', borderRadius: '4px', outline: 'none' }} value={leg.type} onChange={e => updateLeg(leg.id, 'type', e.target.value)}>
                        <option value="CE">CE</option>
                        <option value="PE">PE</option>
                      </select>
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      {/* Constrained to strikes that actually exist in the
                          chain, so a leg can never reference a contract with
                          no price. Falls back to a stepped number input only
                          when no chain is loaded. */}
                      {strikes.length ? (
                        <select
                          style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px', borderRadius: '4px', width: '92px', textAlign: 'center', outline: 'none' }}
                          value={leg.strike}
                          onChange={e => updateLeg(leg.id, 'strike', parseFloat(e.target.value))}
                        >
                          {!strikes.includes(leg.strike) && (
                            <option value={leg.strike}>{leg.strike} (off-chain)</option>
                          )}
                          {strikes.map(s => (
                            <option key={s} value={s}>
                              {s}{s === nearestStrike(spotPrice) ? ' · ATM' : ''}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input type="number" style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px', borderRadius: '4px', width: '92px', textAlign: 'center', outline: 'none' }} value={leg.strike} onChange={e => updateLeg(leg.id, 'strike', parseFloat(e.target.value) || 0)} step={strikeStep} />
                      )}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <input
                        type="number"
                        title={leg.unquoted
                          ? 'No quote for this contract in the loaded chain — value entered manually'
                          : 'Live premium from the options chain'}
                        style={{ backgroundColor: 'var(--bg-tertiary)', border: `1px solid ${leg.unquoted ? 'var(--accent-yellow)' : 'var(--border-color)'}`, color: leg.unquoted ? 'var(--accent-yellow)' : 'var(--text-primary)', padding: '4px', borderRadius: '4px', width: '80px', textAlign: 'center', outline: 'none' }}
                        value={leg.premium}
                        onChange={e => updateLeg(leg.id, 'premium', parseFloat(e.target.value) || 0)}
                      />
                    </td>
                    <td style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>{leg.iv.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Bottom: Analytics & Payoff */}
      <div style={{ flex: 1.2, display: 'flex', flexDirection: 'row', overflow: 'hidden' }}>
        
        {/* Payoff Graph */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border-color)' }}>
          <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'var(--bg-tertiary)', padding: '8px 16px', borderBottom: '1px solid var(--border-color)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 600 }}>
              <Activity size={16} color="var(--accent-green-light)" />
              Payoff Chart
            </div>
            
            {/* Quick settings for chart */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
              {chain?.underlying && (
                <span className="badge badge-blue" style={{ fontSize: '10px', padding: '2px 6px' }}>
                  {chain.underlying}
                </span>
              )}
              <span style={{ color: 'var(--text-secondary)' }}>Spot:</span>
              <input
                type="number"
                title={spotOverride === null ? 'Live spot from the options chain' : 'Manual override'}
                style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--accent-yellow)', padding: '2px 4px', borderRadius: '4px', width: '76px', textAlign: 'center', outline: 'none' }}
                value={Number.isFinite(spotPrice) ? Number(spotPrice.toFixed(2)) : 0}
                onChange={e => setSpotOverride(parseFloat(e.target.value) || 0)}
                step={strikeStep}
              />
              {spotOverride !== null && chain?.spotPrice ? (
                <button className="btn btn-sm btn-ghost" style={{ fontSize: '10px', padding: '2px 6px' }}
                        onClick={() => setSpotOverride(null)} title="Use live chain spot">
                  live
                </button>
              ) : null}
              <span style={{ color: 'var(--text-secondary)', marginLeft: '4px' }}>Lot Size:</span>
              <input type="number" style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '2px 4px', borderRadius: '4px', width: '48px', textAlign: 'center', outline: 'none' }} value={lotSize} onChange={e => setLotOverride(parseInt(e.target.value) || 1)} min="1" />
            </div>
          </div>
          <div style={{ flex: 1, padding: '16px' }}>
            <PayoffChart strategyPositions={legs} underlyingPrice={spotPrice} lotSize={lotSize} />
          </div>
        </div>

        {/* Analytics Sidebar */}
        <div style={{ width: '280px', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--bg-secondary)', borderLeft: '1px solid var(--border-color)' }}>
          <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: 'var(--bg-tertiary)', padding: '8px 16px', borderBottom: '1px solid var(--border-color)' }}>
            <Settings2 size={16} color="var(--accent-yellow)" />
            <span style={{ fontSize: '13px', fontWeight: 600 }}>Risk & Analytics</span>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            
            <GreeksPanel legs={legs} lotSize={lotSize} />

            <div style={{ height: '1px', backgroundColor: 'var(--border-color)' }}></div>

            {/* Shared assumptions driving both risk models below */}
            <div className="flex-col gap-2">
              <span className="text-muted" style={{ fontSize: '12px' }}>Model Assumptions</span>
              <div style={{ display: 'flex', gap: '8px' }}>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>IV (%)</label>
                  <input
                    type="number" step="0.1" min="0.1"
                    style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px', borderRadius: '4px', width: '100%', outline: 'none' }}
                    value={iv.toFixed(1)}
                    onChange={e => setIvOverride(parseFloat(e.target.value) || null)}
                  />
                </div>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Days to Expiry</label>
                  <input
                    type="number" step="1" min="0"
                    style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px', borderRadius: '4px', width: '100%', outline: 'none' }}
                    value={dte}
                    onChange={e => setDteOverride(Math.max(0, parseInt(e.target.value) || 0))}
                  />
                </div>
              </div>
              {ivOverride !== null && (
                <button
                  className="btn btn-sm btn-ghost"
                  style={{ fontSize: '11px', alignSelf: 'flex-start' }}
                  onClick={() => setIvOverride(null)}
                >
                  Reset to chain IV ({impliedIv.toFixed(1)}%)
                </button>
              )}
            </div>

            <div style={{ height: '1px', backgroundColor: 'var(--border-color)' }}></div>

            <StressTestPanel legs={legs} spotPrice={spotPrice} lotSize={lotSize} iv={iv} dte={dte} />

            <div style={{ height: '1px', backgroundColor: 'var(--border-color)' }}></div>

            <MonteCarloPanel legs={legs} spotPrice={spotPrice} lotSize={lotSize} iv={iv} dte={dte} />

          </div>
        </div>
        
      </div>
    </div>
  );
}
