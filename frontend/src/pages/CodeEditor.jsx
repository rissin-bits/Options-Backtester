import { useState, useRef, useEffect } from 'react';
import Editor from '@monaco-editor/react';

const TEMPLATE_STRATEGIES = {
  'Short Straddle': `"""
Short Straddle Strategy — Sell ATM CE + PE at market open.

This strategy sells both ATM Call and Put options at 9:20 AM,
collecting theta decay throughout the day, and squares off
at 3:15 PM or on hitting the stop loss.
"""
from datetime import time
from backend.strategy import (
    Strategy, Order, MarketContext, Side, OptionType, StrikeSelection,
)
from typing import List, Union


class ShortStraddleStrategy(Strategy):
    name = "Short Straddle 9:20"
    description = "Sell ATM CE + PE at 9:20, exit at 15:15 or SL"

    def __init__(self, entry_time="09:20", exit_time="15:15", sl_pct=30.0):
        self.entry_time = time(*map(int, entry_time.split(":")))
        self.exit_time = time(*map(int, exit_time.split(":")))
        self.sl_pct = sl_pct

    def on_candle(self, ctx: MarketContext) -> Union[List[Order], str, None]:
        # Square off at exit time
        if ctx.time_of_day >= self.exit_time and ctx.positions:
            return "SQUARE_OFF_ALL"

        # Check stop loss on existing positions
        if ctx.positions:
            total_entry = sum(p.entry_price * p.quantity for p in ctx.positions)
            total_current = sum(p.current_price * p.quantity for p in ctx.positions)
            if total_entry > 0:
                # For short positions, loss = current > entry
                loss_pct = ((total_current - total_entry) / total_entry) * 100
                if loss_pct >= self.sl_pct:
                    return "SQUARE_OFF_ALL"
            return None

        # Entry at specified time
        if ctx.time_of_day >= self.entry_time and not ctx.positions:
            return [
                Order(Side.SELL, OptionType.CE, StrikeSelection.ATM, tag="straddle_ce"),
                Order(Side.SELL, OptionType.PE, StrikeSelection.ATM, tag="straddle_pe"),
            ]

        return None
`,

  'VWAP Breakout': `"""
VWAP Breakout Strategy — Buy options based on VWAP crossover.

When spot price crosses above VWAP → Buy CE
When spot price crosses below VWAP → Buy PE
"""
from datetime import time
from backend.strategy import (
    Strategy, Order, MarketContext, Side, OptionType, StrikeSelection,
)
from typing import List, Union


class VWAPBreakoutStrategy(Strategy):
    name = "VWAP Breakout"
    description = "Buy CE/PE on VWAP crossover"

    def __init__(self):
        self.prev_spot = None
        self.prev_vwap = None

    def required_indicators(self):
        return [
            {"name": "VWAP", "params": {"reset_daily": True}, "input": "close"},
        ]

    def on_candle(self, ctx: MarketContext) -> Union[List[Order], str, None]:
        vwap = ctx.indicators.get("VWAP_reset_dailyTrue")
        if vwap is None:
            return None

        # Exit at 15:15
        if ctx.time_of_day >= time(15, 15) and ctx.positions:
            return "SQUARE_OFF_ALL"

        # Stop loss / target
        if ctx.positions:
            for pos in ctx.positions:
                pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100
                if pos.side == Side.SELL:
                    pnl_pct = -pnl_pct
                if pnl_pct <= -3.0 or pnl_pct >= 5.0:
                    return "SQUARE_OFF_ALL"
            self.prev_spot = ctx.spot_price
            self.prev_vwap = vwap
            return None

        # Wait for 9:30
        if ctx.time_of_day < time(9, 30):
            self.prev_spot = ctx.spot_price
            self.prev_vwap = vwap
            return None

        # Crossover logic
        if self.prev_spot and self.prev_vwap:
            if self.prev_spot <= self.prev_vwap and ctx.spot_price > vwap:
                self.prev_spot = ctx.spot_price
                self.prev_vwap = vwap
                return [Order(Side.BUY, OptionType.CE, StrikeSelection.ATM)]
            if self.prev_spot >= self.prev_vwap and ctx.spot_price < vwap:
                self.prev_spot = ctx.spot_price
                self.prev_vwap = vwap
                return [Order(Side.BUY, OptionType.PE, StrikeSelection.ATM)]

        self.prev_spot = ctx.spot_price
        self.prev_vwap = vwap
        return None

    def on_day_start(self, ctx):
        self.prev_spot = None
        self.prev_vwap = None
`,

  'RSI Mean Reversion': `"""
RSI Mean Reversion Strategy — Buy oversold, sell overbought.
"""
from datetime import time
from backend.strategy import (
    Strategy, Order, MarketContext, Side, OptionType, StrikeSelection,
)
from typing import List, Union


class RSIMeanReversion(Strategy):
    name = "RSI Mean Reversion"
    description = "Buy CE when RSI < 30, exit when RSI > 70"

    def __init__(self, rsi_period=14, oversold=30, overbought=70):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought

    def required_indicators(self):
        return [
            {"name": "RSI", "params": {"period": self.rsi_period}, "input": "close"},
        ]

    def on_candle(self, ctx: MarketContext) -> Union[List[Order], str, None]:
        rsi = ctx.indicators.get(f"RSI_period{self.rsi_period}")

        # Square off at 15:15
        if ctx.time_of_day >= time(15, 15) and ctx.positions:
            return "SQUARE_OFF_ALL"

        if rsi is None:
            return None

        # Exit when overbought
        if ctx.positions and rsi > self.overbought:
            return "SQUARE_OFF_ALL"

        # Enter when oversold
        if not ctx.positions and rsi < self.oversold:
            if time(9, 30) <= ctx.time_of_day <= time(14, 30):
                return [Order(Side.BUY, OptionType.CE, StrikeSelection.ATM)]

        return None
`,

  'Blank Template': `"""
Custom Strategy Template — Write your own logic.

Subclass Strategy and implement on_candle() to define your rules.
"""
from datetime import time
from backend.strategy import (
    Strategy, Order, MarketContext, Side, OptionType, StrikeSelection,
)
from typing import List, Union


class MyCustomStrategy(Strategy):
    name = "My Custom Strategy"
    description = "Describe your strategy here"

    def __init__(self):
        # Initialize any state variables
        pass

    def required_indicators(self):
        """Return list of indicators your strategy needs."""
        return [
            # {"name": "RSI", "params": {"period": 14}, "input": "close"},
            # {"name": "SMA", "params": {"period": 20}, "input": "close"},
        ]

    def on_candle(self, ctx: MarketContext) -> Union[List[Order], str, None]:
        """
        Called on every candle. Return:
          - List[Order] to place orders
          - "SQUARE_OFF_ALL" to close all positions
          - None for no action

        ctx contains:
          - ctx.timestamp, ctx.spot_price, ctx.time_of_day
          - ctx.options_chain (full chain DataFrame)
          - ctx.positions (open positions list)
          - ctx.indicators (pre-computed indicator values)
          - ctx.day_pnl, ctx.total_pnl
          - ctx.trading_day, ctx.days_to_expiry
        """

        # Example: Simple time-based entry and exit
        # if ctx.time_of_day >= time(9, 20) and not ctx.positions:
        #     return [Order(Side.SELL, OptionType.CE, StrikeSelection.ATM)]
        #
        # if ctx.time_of_day >= time(15, 15) and ctx.positions:
        #     return "SQUARE_OFF_ALL"

        return None

    def on_day_start(self, ctx: MarketContext):
        """Called at start of each trading day."""
        pass

    def on_day_end(self, ctx: MarketContext):
        """Called at end of each trading day."""
        pass
`,
};

export default function CodeEditor() {
  const [code, setCode] = useState(TEMPLATE_STRATEGIES['Blank Template']);
  const [selectedTemplate, setSelectedTemplate] = useState('Blank Template');
  const [output, setOutput] = useState('');
  const [showOutput, setShowOutput] = useState(false);

  const handleTemplateChange = (template) => {
    setSelectedTemplate(template);
    setCode(TEMPLATE_STRATEGIES[template]);
  };

  const handleValidate = () => {
    try {
      // Basic Python syntax validation (check for common issues)
      const issues = [];
      if (!code.includes('class ') || !code.includes('Strategy')) {
        issues.push('⚠️ Strategy class not found. Your strategy must subclass Strategy.');
      }
      if (!code.includes('on_candle')) {
        issues.push('⚠️ on_candle method not found. This is required.');
      }
      if (!code.includes('def on_candle')) {
        issues.push('⚠️ on_candle must be defined as a method.');
      }

      if (issues.length === 0) {
        setOutput('✅ Strategy looks valid! No issues found.\n\nTo run this strategy:\n1. Save the file to backend/custom_strategies/\n2. Import it in the backend\n3. Run via the API or CLI');
      } else {
        setOutput(issues.join('\n'));
      }
      setShowOutput(true);
    } catch (e) {
      setOutput(`❌ Error: ${e.message}`);
      setShowOutput(true);
    }
  };

  const handleSave = () => {
    const blob = new Blob([code], { type: 'text/python' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'my_strategy.py';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <header className="header">
        <h2 className="header-title">💻 Code Editor</h2>
        <div className="header-actions">
          <select className="form-select" value={selectedTemplate}
            onChange={e => handleTemplateChange(e.target.value)}
            style={{ width: 'auto', minWidth: '180px', padding: '6px 32px 6px 12px' }}>
            {Object.keys(TEMPLATE_STRATEGIES).map(t =>
              <option key={t} value={t}>{t}</option>
            )}
          </select>
          <button className="btn btn-sm btn-ghost" onClick={handleValidate}>✓ Validate</button>
          <button className="btn btn-sm btn-ghost" onClick={handleSave}>💾 Download .py</button>
          <button className="btn btn-sm btn-primary" onClick={() => {
            setOutput('🚀 To run custom code strategies, start the backend server\nfrom the REPOSITORY ROOT (not inside backend/ — the package uses\nabsolute "backend.*" imports):\n\n  python -m uvicorn backend.api:app --reload --port 8000\n\nThen use the API:\n  POST /api/backtest with your strategy config');
            setShowOutput(true);
          }}>
            ▶ Run
          </button>
        </div>
      </header>

      <div className="page-container" style={{ padding: '0 32px 24px' }}>
        <div style={{
          display: 'grid',
          gridTemplateRows: showOutput ? '1fr 200px' : '1fr',
          gap: '0',
          height: 'calc(100vh - var(--header-height) - 24px)',
        }}>
          {/* Editor */}
          <div style={{
            borderRadius: 'var(--radius-lg)',
            overflow: 'hidden',
            border: '1px solid var(--border-color)',
          }}>
            <Editor
              height="100%"
              language="python"
              theme="vs-dark"
              value={code}
              onChange={setCode}
              options={{
                fontSize: 14,
                fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                padding: { top: 16 },
                lineNumbers: 'on',
                renderLineHighlight: 'all',
                smoothScrolling: true,
                cursorBlinking: 'smooth',
                bracketPairColorization: { enabled: true },
                automaticLayout: true,
              }}
            />
          </div>

          {/* Output panel */}
          {showOutput && (
            <div style={{
              background: 'var(--bg-primary)',
              border: '1px solid var(--border-color)',
              borderTop: 'none',
              borderRadius: '0 0 var(--radius-lg) var(--radius-lg)',
              overflow: 'auto',
            }}>
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '8px 16px',
                borderBottom: '1px solid var(--border-subtle)',
                background: 'rgba(255,255,255,0.02)',
              }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                  Output
                </span>
                <button className="btn btn-sm btn-ghost" onClick={() => setShowOutput(false)}
                  style={{ padding: '2px 8px' }}>✕</button>
              </div>
              <pre style={{
                padding: '12px 16px',
                fontSize: '13px',
                fontFamily: 'var(--font-mono)',
                color: 'var(--accent-gold-light)',
                whiteSpace: 'pre-wrap',
                margin: 0,
              }}>
                {output}
              </pre>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
