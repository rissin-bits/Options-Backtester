"""
stress_test.py — Scenario analysis and stress testing engine.

Applies instantaneous shocks to spot price and implied volatility 
to calculate the portfolio's expected P&L and Greeks impact.
"""
from typing import List, Dict, Any
from backend.greeks import black_scholes

SCENARIOS = [
    {"name": "Black Swan", "spot_shock": -0.20, "iv_shock": 1.00},  # -20% spot, +100% IV
    {"name": "COVID Crash", "spot_shock": -0.35, "iv_shock": 1.50}, # -35% spot, +150% IV
    {"name": "Flash Crash", "spot_shock": -0.10, "iv_shock": 0.80}, # -10% spot, +80% IV
    {"name": "Gap Up", "spot_shock": 0.05, "iv_shock": -0.10},      # +5% spot, -10% IV
    {"name": "Gap Down", "spot_shock": -0.05, "iv_shock": 0.20},    # -5% spot, +20% IV
    {"name": "IV Expansion", "spot_shock": 0.00, "iv_shock": 0.50}, # 0% spot, +50% IV
    {"name": "IV Crush", "spot_shock": 0.00, "iv_shock": -0.30},    # 0% spot, -30% IV
]

def evaluate_scenario(
    current_spot: float,
    current_iv: float,
    days_to_expiry: int,
    legs: List[Dict[str, Any]],
    spot_shock: float,
    iv_shock: float,
    lot_size: int = 1,
    risk_free_rate: float = 0.065
) -> Dict[str, Any]:
    """
    Evaluates a specific stress test scenario on a strategy.
    Shocks are relative percentages (e.g., -0.10 means -10%).
    """
    T = max(days_to_expiry / 365.0, 1e-5)
    
    new_spot = current_spot * (1 + spot_shock)
    new_iv = max(current_iv * (1 + iv_shock), 0.01) # Floor IV at 1%
    
    total_pnl = 0
    new_delta = 0
    new_gamma = 0
    new_theta = 0
    new_vega = 0
    
    for leg in legs:
        strike = leg['strike']
        side_mult = 1 if leg['side'] == 'BUY' else -1
        opt_type = leg['type']
        flag = 'c' if opt_type == 'CE' else 'p'
        qty = leg.get('qty', 1) * lot_size
        entry_premium = leg['premium']
        
        # Original position notional value
        original_notional = entry_premium * qty * side_mult
        
        # Calculate new price and greeks using Black-Scholes
        try:
            greeks = black_scholes(flag, new_spot, strike, T, risk_free_rate, new_iv)
            new_price = greeks["price"]
            
            pnl = (new_price - entry_premium) * side_mult * qty
            total_pnl += pnl
            
            new_delta += greeks["delta"] * side_mult * qty
            new_gamma += greeks["gamma"] * side_mult * qty
            new_theta += greeks["theta"] * side_mult * qty
            new_vega += greeks["vega"] * side_mult * qty
        except Exception:
            pass # Ignore legs that fail to compute (e.g. extreme out of bounds)
            
    return {
        "spot": new_spot,
        "iv": new_iv,
        "pnl": total_pnl,
        "greeks": {
            "delta": new_delta,
            "gamma": new_gamma,
            "theta": new_theta,
            "vega": new_vega
        }
    }

def run_stress_tests(
    current_spot: float,
    current_iv: float,
    days_to_expiry: int,
    legs: List[Dict[str, Any]],
    lot_size: int = 1,
    custom_scenarios: List[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Run all preset and custom stress test scenarios.
    """
    scenarios_to_run = SCENARIOS.copy()
    if custom_scenarios:
        scenarios_to_run.extend(custom_scenarios)
        
    results = []
    for scen in scenarios_to_run:
        res = evaluate_scenario(
            current_spot, current_iv, days_to_expiry, legs, 
            scen["spot_shock"], scen["iv_shock"], lot_size
        )
        results.append({
            "name": scen["name"],
            "spot_shock": scen["spot_shock"],
            "iv_shock": scen["iv_shock"],
            "result": res
        })
        
    return results
