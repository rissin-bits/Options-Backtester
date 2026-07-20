import React, { useState, useEffect, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { API_BASE } from '../App';

/**
 * Extract "HH:MM:SS" from a backend timestamp.
 * The API returns ISO-8601 ("2024-01-02T09:20:00"), but tolerate a space
 * separator too so the time picker degrades gracefully rather than rendering
 * a list of `undefined` options.
 */
function timeOfDay(ts) {
  if (typeof ts !== 'string') return '';
  const match = ts.match(/[T ](\d{2}:\d{2}:\d{2})/);
  return match ? match[1] : '';
}

/*
 * Column geometry, shared by the header and the virtualized body.
 *
 * These MUST come from one place. Flex items default to `min-width: auto`, so a
 * cell never shrinks below its own content. The header was therefore sized by
 * its labels ("Gamma", "Theta") while each body row was sized by its own numbers
 * ("162300", "12074.05") — two independent flex containers resolving to
 * different widths, so no column lined up with its heading and rows drifted
 * against each other. `minWidth: 0` makes the flex ratio govern instead.
 */
const NUM_CELL = {
  flex: 1,
  minWidth: 0,
  overflow: 'hidden',
  whiteSpace: 'nowrap',
  textOverflow: 'ellipsis',
  textAlign: 'right',
};

// The LTP cell also holds the B/S buttons, so it needs a real floor. Header and
// body both use it, which is what keeps them aligned.
const LTP_CELL = { flex: 1.5, minWidth: '130px' };

const STRIKE_CELL = { width: '80px', flexShrink: 0 };

// Below this width the columns stop being readable, so scroll the table as a
// unit rather than squashing it. Header and body share a scroll parent, so the
// headings stay over their data when scrolled sideways.
const TABLE_MIN_WIDTH = '1280px';

// Buy/Sell quick-add buttons: rectangular rather than pill-shaped, and large
// enough to be a comfortable click target in a dense 35px row.
const BS_BUTTON = {
  padding: '4px 9px',
  fontSize: '11px',
  fontWeight: 700,
  lineHeight: 1,
  borderRadius: '3px',
  minWidth: '26px',
};

export default function OptionsChain({ onAddLeg }) {
  const [underlyings, setUnderlyings] = useState([]);
  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY');
  
  const [tradingDates, setTradingDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState('');
  
  const [timestamps, setTimestamps] = useState([]);
  const [selectedTime, setSelectedTime] = useState('');
  
  const [expiries, setExpiries] = useState([]);
  const [selectedExpiry, setSelectedExpiry] = useState('');
  
  // Cache chains by key
  const [chainCache, setChainCache] = useState({});
  const [currentChainKey, setCurrentChainKey] = useState(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const parentRef = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/data/underlyings`)
      .then(res => res.json())
      .then(data => {
        setUnderlyings(data);
        if (data.length > 0) setSelectedUnderlying(data[0].name);
      })
      .catch(err => console.error(err));
  }, []);

  useEffect(() => {
    if (!selectedUnderlying) return;
    fetch(`${API_BASE}/api/data/trading-dates?underlying=${selectedUnderlying}`)
      .then(res => res.json())
      .then(data => {
        setTradingDates(data.map(d => d.date));
        if (data.length > 0) setSelectedDate(data[data.length - 1].date);
      })
      .catch(err => console.error(err));
  }, [selectedUnderlying]);

  useEffect(() => {
    if (!selectedUnderlying || !selectedDate) return;
    
    fetch(`${API_BASE}/api/data/expiries?underlying=${selectedUnderlying}&date=${selectedDate}`)
      .then(res => res.json())
      .then(data => {
        setExpiries(data);
        if (data.length > 0) setSelectedExpiry(data[0].expiry);
      });

    fetch(`${API_BASE}/api/data/timestamps?underlying=${selectedUnderlying}&date=${selectedDate}`)
      .then(res => res.json())
      .then(data => {
        setTimestamps(data);
        if (data.length > 0) setSelectedTime(timeOfDay(data[0]));
      });
  }, [selectedUnderlying, selectedDate]);

  useEffect(() => {
    if (!selectedUnderlying || !selectedDate || !selectedExpiry) return;
    
    const key = `${selectedUnderlying}_${selectedDate}_${selectedExpiry}_${selectedTime}`;
    setCurrentChainKey(key);

    if (chainCache[key]) {
      return;
    }
    
    setLoading(true);
    setError(null);
    
    fetch(`${API_BASE}/api/data/options-chain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        underlying: selectedUnderlying,
        date: selectedDate,
        time: selectedTime || null,
        expiry: selectedExpiry
      })
    })
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then(data => {
      const strikesMap = {};
      data.chain.forEach(opt => {
        if (!strikesMap[opt.strike]) {
          strikesMap[opt.strike] = { strike: opt.strike };
        }
        if (opt.option_type === 'CE') {
          strikesMap[opt.strike].CE = opt;
        } else {
          strikesMap[opt.strike].PE = opt;
        }
      });
      
      const chainList = Object.values(strikesMap).sort((a, b) => a.strike - b.strike);
      
      setChainCache(prev => ({
        ...prev,
        [key]: { chain: chainList, spotPrice: data.spot_price }
      }));
    })
    .catch(err => setError(err.message))
    .finally(() => setLoading(false));
  }, [selectedUnderlying, selectedDate, selectedExpiry, selectedTime, chainCache]);

  const currentData = currentChainKey && chainCache[currentChainKey] ? chainCache[currentChainKey] : null;
  const chainData = currentData?.chain || [];
  const spotPrice = currentData?.spotPrice || 0;
  
  const rowVirtualizer = useVirtualizer({
    count: chainData.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 35,
    overscan: 5,
  });

  useEffect(() => {
    if (chainData.length > 0 && spotPrice && parentRef.current) {
      let atmIndex = 0;
      let minDiff = Infinity;
      for (let i=0; i<chainData.length; i++) {
        const diff = Math.abs(chainData[i].strike - spotPrice);
        if (diff < minDiff) {
          minDiff = diff;
          atmIndex = i;
        }
      }
      rowVirtualizer.scrollToIndex(Math.max(0, atmIndex - 10), { align: 'start' });
    }
  }, [chainData, spotPrice]); // Removed rowVirtualizer dependency to avoid scrolling on every render

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ padding: '16px', display: 'flex', flexWrap: 'wrap', gap: '16px', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-tertiary)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600 }}>Underlying</label>
          <select style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: '4px', outline: 'none' }} value={selectedUnderlying} onChange={e => setSelectedUnderlying(e.target.value)}>
            {underlyings.map(u => <option key={u.name} value={u.name}>{u.name}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600 }}>Date</label>
          <select style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: '4px', outline: 'none' }} value={selectedDate} onChange={e => setSelectedDate(e.target.value)}>
            {tradingDates.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600 }}>Time (1-Min)</label>
          <select style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: '4px', outline: 'none' }} value={selectedTime} onChange={e => setSelectedTime(e.target.value)}>
            <option value="">End of Day</option>
            {timestamps.map(t => {
              const timeStr = timeOfDay(t);
              return timeStr ? <option key={timeStr} value={timeStr}>{timeStr}</option> : null;
            })}
          </select>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600 }}>Expiry</label>
          <select style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: '4px', outline: 'none' }} value={selectedExpiry} onChange={e => setSelectedExpiry(e.target.value)}>
            {expiries.map(e => <option key={e.expiry} value={e.expiry}>{e.expiry} {e.dte != null ? `(${e.dte}d)` : ''}</option>)}
          </select>
        </div>
        
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600 }}>Spot Price</span>
            <span style={{ fontSize: '16px', fontWeight: 700, color: 'var(--accent-yellow)' }}>
              {spotPrice ? spotPrice.toFixed(2) : '---'}
            </span>
          </div>
        </div>
      </div>

      <div style={{ position: 'relative', flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {loading && (
          <div className="loading-overlay">
            Loading chain...
          </div>
        )}
        
        {error && (
          <div style={{ padding: '12px', background: 'var(--accent-red-dark)', color: '#fff', textAlign: 'center' }}>
            {error}
          </div>
        )}

        {/* Horizontal scroller wrapping BOTH header and body, so headings stay
            over their columns when the table is scrolled sideways. */}
        <div style={{ flex: 1, minHeight: 0, overflowX: 'auto', overflowY: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ minWidth: TABLE_MIN_WIDTH, flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>

        <div style={{ display: 'flex', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-header)', fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>
          <div style={{ flex: 1, display: 'flex', minWidth: 0 }}>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Delta</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Gamma</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Theta</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Vega</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>IV %</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Vol</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>OI</span>
            <span style={{ ...LTP_CELL, padding: '10px 8px', borderRight: '1px solid var(--border-color)', textAlign: 'center' }}>CALLS LTP</span>
          </div>
          <div style={{ ...STRIKE_CELL, padding: '10px 8px', textAlign: 'center' }}>STRIKE</div>
          <div style={{ flex: 1, display: 'flex', minWidth: 0 }}>
            <span style={{ ...LTP_CELL, padding: '10px 8px', borderLeft: '1px solid var(--border-color)', textAlign: 'center' }}>PUTS LTP</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>OI</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Vol</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>IV %</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Vega</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Theta</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Gamma</span>
            <span style={{ ...NUM_CELL, padding: '10px 8px' }}>Delta</span>
          </div>
        </div>

        <div
          ref={parentRef}
          style={{ flex: 1, minHeight: 0, fontSize: '13px', fontFamily: 'var(--font-mono)', overflowY: 'auto', overflowX: 'hidden' }}
        >
          {chainData.length > 0 ? (
            <div
              style={{
                height: `${rowVirtualizer.getTotalSize()}px`,
                width: '100%',
                position: 'relative',
              }}
            >
              {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                const row = chainData[virtualRow.index];
                const ce = row.CE || {};
                const pe = row.PE || {};
                const isAtm = spotPrice && Math.abs(row.strike - spotPrice) <= 25;
                
                return (
                  <div
                    key={virtualRow.index}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: `${virtualRow.size}px`,
                      transform: `translateY(${virtualRow.start}px)`,
                      display: 'flex', 
                      borderBottom: '1px solid var(--border-color)', 
                      backgroundColor: isAtm ? 'rgba(245, 158, 11, 0.1)' : 'transparent'
                    }}
                    className="chain-row"
                  >
                    <div style={{ flex: 1, display: 'flex', minWidth: 0 }}>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={ce.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{ce.delta?.toFixed(2) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={ce.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{ce.gamma?.toFixed(4) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={ce.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{ce.theta?.toFixed(2) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={ce.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{ce.vega?.toFixed(2) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={ce.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{ce.iv?.toFixed(1) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={ce.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{ce.volume || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={ce.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{ce.oi || '-'}</span>
                      <div style={{ ...LTP_CELL, padding: '8px', fontWeight: 600, borderRight: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }} className={ce.moneyness === 'ITM' ? 'itm text-green' : 'text-green'}>
                        <span>{ce.close?.toFixed(2) || '-'}</span>
                        <div style={{ display: 'flex', gap: '2px' }}>
                          <button className="btn btn-sm btn-success" style={BS_BUTTON} onClick={() => onAddLeg?.({ type: 'CE', side: 'BUY', strike: row.strike, premium: ce.close, delta: ce.delta, gamma: ce.gamma, theta: ce.theta, vega: ce.vega, iv: ce.iv })}>B</button>
                          <button className="btn btn-sm btn-danger" style={BS_BUTTON} onClick={() => onAddLeg?.({ type: 'CE', side: 'SELL', strike: row.strike, premium: ce.close, delta: ce.delta, gamma: ce.gamma, theta: ce.theta, vega: ce.vega, iv: ce.iv })}>S</button>
                        </div>
                      </div>
                    </div>
                    
                    <div style={{ ...STRIKE_CELL, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, backgroundColor: isAtm ? 'rgba(245, 158, 11, 0.2)' : 'rgba(255, 255, 255, 0.02)', color: isAtm ? 'var(--accent-yellow)' : 'var(--text-primary)' }}>
                      {row.strike}
                    </div>
                    
                    <div style={{ flex: 1, display: 'flex', minWidth: 0 }}>
                      <div style={{ ...LTP_CELL, padding: '8px', fontWeight: 600, borderLeft: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }} className={pe.moneyness === 'ITM' ? 'itm text-red' : 'text-red'}>
                        <div style={{ display: 'flex', gap: '2px' }}>
                          <button className="btn btn-sm btn-success" style={BS_BUTTON} onClick={() => onAddLeg?.({ type: 'PE', side: 'BUY', strike: row.strike, premium: pe.close, delta: pe.delta, gamma: pe.gamma, theta: pe.theta, vega: pe.vega, iv: pe.iv })}>B</button>
                          <button className="btn btn-sm btn-danger" style={BS_BUTTON} onClick={() => onAddLeg?.({ type: 'PE', side: 'SELL', strike: row.strike, premium: pe.close, delta: pe.delta, gamma: pe.gamma, theta: pe.theta, vega: pe.vega, iv: pe.iv })}>S</button>
                        </div>
                        <span>{pe.close?.toFixed(2) || '-'}</span>
                      </div>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={pe.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{pe.oi || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={pe.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{pe.volume || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={pe.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{pe.iv?.toFixed(1) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={pe.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{pe.vega?.toFixed(2) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={pe.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{pe.theta?.toFixed(2) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={pe.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{pe.gamma?.toFixed(4) || '-'}</span>
                      <span style={{ ...NUM_CELL, padding: '8px' }} className={pe.moneyness === 'ITM' ? 'itm text-muted' : 'text-muted'}>{pe.delta?.toFixed(2) || '-'}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            !loading && (
              <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-tertiary)' }}>
                No options data available for this selection
              </div>
            )
          )}
        </div>

        </div>{/* min-width table */}
        </div>{/* horizontal scroller */}
      </div>
    </div>
  );
}
