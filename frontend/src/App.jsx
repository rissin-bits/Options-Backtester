import { useState, useEffect, useRef } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import OptionsChain from './pages/OptionsChain';
import StrategyBuilder from './pages/StrategyBuilder';
import BacktestModal from './components/BacktestModal';
import Dashboard from './pages/Dashboard';
import Results from './pages/Results';
import CodeEditor from './pages/CodeEditor';
import BacktestRunner from './pages/BacktestRunner';
import { Settings, Play, Code2, BarChart3, LayoutDashboard, Terminal, FlaskConical } from 'lucide-react';
import './index.css';

const API_BASE = 'http://localhost:8000';

function StatusIndicator() {
  const [status, setStatus] = useState('Checking...');
  const [color, setColor] = useState('#8b949e');

  useEffect(() => {
    fetch(`${API_BASE}/api/status`)
      .then(res => res.json())
      .then(data => {
        if (data.status === 'healthy') {
          setStatus(data.data_available ? 'Connected' : 'No Data');
          setColor(data.data_available ? '#3fb950' : '#d29922');
        } else {
          setStatus('Error');
          setColor('#f85149');
        }
      })
      .catch(() => {
        setStatus('Offline');
        setColor('#f85149');
      });
  }, []);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
      <div style={{
        width: '8px', height: '8px', borderRadius: '50%', backgroundColor: color,
        boxShadow: `0 0 6px ${color}44`,
      }}></div>
      <span style={{ color }}>{status}</span>
    </div>
  );
}

const SPLIT_MIN = 25;
const SPLIT_MAX = 75;
const SPLIT_DEFAULT = 55;

function Workspace({ legs, setLegs, handleAddLeg }) {
  const containerRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [splitPct, setSplitPct] = useState(() => {
    const saved = parseFloat(localStorage.getItem('workspaceSplit'));
    return Number.isFinite(saved)
      ? Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, saved))
      : SPLIT_DEFAULT;
  });

  useEffect(() => {
    if (!dragging) return;

    const onMove = (e) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect || !rect.width) return;
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setSplitPct(Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, pct)));
    };
    const stop = () => setDragging(false);

    // Listen on window so the drag survives the cursor leaving the handle.
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', stop);
    // Stop the browser text-selecting the whole page mid-drag.
    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', stop);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
    };
  }, [dragging]);

  useEffect(() => {
    localStorage.setItem('workspaceSplit', String(splitPct));
  }, [splitPct]);

  return (
    <div
      className="workspace-content"
      ref={containerRef}
      style={{ '--split': `${splitPct}%` }}
    >
      {/* Left Panel: Options Chain */}
      <div className="workspace-left">
        <OptionsChain onAddLeg={handleAddLeg} />
      </div>

      <div
        className={`workspace-splitter${dragging ? ' dragging' : ''}`}
        onMouseDown={(e) => { e.preventDefault(); setDragging(true); }}
        onDoubleClick={() => setSplitPct(SPLIT_DEFAULT)}
        role="separator"
        aria-orientation="vertical"
        aria-valuenow={Math.round(splitPct)}
        title="Drag to resize · double-click to reset"
      />

      {/* Right Panel: Builder & Analytics */}
      <div className="workspace-right">
        <StrategyBuilder legs={legs} setLegs={setLegs} />
      </div>
    </div>
  );
}

function App() {
  const [legs, setLegs] = useState([]);
  const [isBacktestModalOpen, setIsBacktestModalOpen] = useState(false);
  const [latestResult, setLatestResult] = useState(null);
  
  const navigate = useNavigate();
  const location = useLocation();
  
  const handleAddLeg = (legParams) => {
    setLegs(prev => [...prev, {
      id: Math.random().toString(36).substr(2, 9),
      ...legParams,
      qty: 1,
      delta: legParams.delta || 0,
      gamma: legParams.gamma || 0,
      theta: legParams.theta || 0,
      vega: legParams.vega || 0,
      iv: legParams.iv || 15.0
    }]);
  };

  const handleResult = (result) => {
    setLatestResult(result);
    setIsBacktestModalOpen(false);
    navigate('/results');
  };

  const navItems = [
    { name: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
    { name: 'Terminal', path: '/', icon: Terminal },
    { name: 'Backtest', path: '/backtest', icon: FlaskConical },
    { name: 'Code', path: '/code', icon: Code2 },
    { name: 'Results', path: '/results', icon: BarChart3 },
  ];

  return (
    <div className="workspace-layout">
      {/* Top Header */}
      <header className="workspace-header">
        <div className="brand">
          <span style={{ fontWeight: 800, color: 'var(--accent-gold)' }}>WSC</span> 
          <span style={{ opacity: 0.8, fontWeight: 500, marginLeft: '6px' }}>Options Backtester</span>
        </div>
        
        {/* Navigation Tabs */}
        <div style={{ display: 'flex', gap: '4px', marginLeft: '32px', flex: 1 }}>
          {navItems.map(tab => {
            const isActive = location.pathname === tab.path;
            const Icon = tab.icon;
            return (
              <button 
                key={tab.name} 
                className={`btn btn-sm ${isActive ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => navigate(tab.path)}
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Icon size={14} />
                {tab.name}
              </button>
            )
          })}
        </div>

        {/* Global Controls / Status */}
        <div className="header-controls">
          <StatusIndicator />
          {location.pathname === '/' && (
            <button className="btn btn-primary btn-sm" onClick={() => setIsBacktestModalOpen(true)}>
              <Play size={14} /> Run Backtest
            </button>
          )}
          <button className="btn btn-ghost btn-sm"><Settings size={14} /></button>
        </div>
      </header>

      {/* Main Content Area */}
      <Routes>
        <Route path="/" element={<Workspace legs={legs} setLegs={setLegs} handleAddLeg={handleAddLeg} />} />
        <Route path="/dashboard" element={<div style={{ flex: 1, overflow: 'auto', backgroundColor: 'var(--background)' }}><Dashboard /></div>} />
        <Route path="/backtest" element={<div style={{ flex: 1, overflow: 'auto', backgroundColor: 'var(--background)' }}><BacktestRunner onResult={handleResult} /></div>} />
        <Route path="/code" element={<div style={{ flex: 1, overflow: 'auto', backgroundColor: 'var(--background)' }}><CodeEditor /></div>} />
        <Route path="/results" element={<div style={{ flex: 1, overflow: 'auto', backgroundColor: 'var(--background)' }}><Results resultsData={latestResult} /></div>} />
      </Routes>

      <BacktestModal 
        isOpen={isBacktestModalOpen} 
        onClose={() => setIsBacktestModalOpen(false)} 
        legs={legs}
        underlying="NIFTY"
        onResult={handleResult}
      />
    </div>
  );
}

export { API_BASE };
export default App;
