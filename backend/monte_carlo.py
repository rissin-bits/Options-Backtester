"""
monte_carlo.py — Monte Carlo simulation engine for options strategies.

Generates random price paths using Geometric Brownian Motion (GBM)
to simulate strategy returns, expected value, and risk metrics.
"""
import numpy as np
from typing import List, Dict, Any
from backend.strategy import Order, Side, OptionType

def simulate_gbm_paths(
    S0: float, 
    mu: float, 
    sigma: float, 
    T: float, 
    n_paths: int, 
    n_steps: int = 1
) -> np.ndarray:
    """
    Generate n_paths of spot prices using Geometric Brownian Motion.
    S0: Initial spot price
    mu: Expected return (drift)
    sigma: Volatility (annualized)
    T: Time to expiry in years
    n_paths: Number of simulations
    """
    dt = T / n_steps
    paths = np.zeros((n_paths, n_steps + 1))
    paths[:, 0] = S0
    
    for t in range(1, n_steps + 1):
        Z = np.random.standard_normal(n_paths)
        paths[:, t] = paths[:, t-1] * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z)
        
    return paths[:, -1]  # Return only the final prices for European expiry payoff

def calculate_strategy_payoff(prices: np.ndarray, legs: List[Dict[str, Any]], lot_size: int = 1) -> np.ndarray:
    """
    Calculate payoff for a strategy across an array of prices at expiry.
    """
    total_pnl = np.zeros_like(prices)
    
    for leg in legs:
        strike = leg['strike']
        side = 1 if leg['side'] == 'BUY' else -1
        opt_type = leg['type']
        premium = leg['premium']
        qty = leg.get('qty', 1) * lot_size
        
        if opt_type == 'CE':
            intrinsic = np.maximum(prices - strike, 0)
        else:
            intrinsic = np.maximum(strike - prices, 0)
            
        pnl = (intrinsic - premium) * side * qty
        total_pnl += pnl
        
    return total_pnl

def run_monte_carlo(
    current_spot: float,
    current_iv: float,
    days_to_expiry: int,
    legs: List[Dict[str, Any]],
    lot_size: int = 1,
    n_simulations: int = 1000,
    risk_free_rate: float = 0.065
) -> Dict[str, Any]:
    """
    Run Monte Carlo simulation for a given strategy and return statistics.
    """
    T = max(days_to_expiry / 365.0, 1/365.0)
    mu = risk_free_rate  # Risk-neutral drift
    
    # Generate expiry spot prices
    final_prices = simulate_gbm_paths(current_spot, mu, current_iv, T, n_simulations)
    
    # Calculate payoffs
    pnls = calculate_strategy_payoff(final_prices, legs, lot_size)
    
    # Calculate statistics
    win_mask = pnls > 0
    prob_profit = np.mean(win_mask) * 100
    expected_value = np.mean(pnls)
    max_loss = np.min(pnls)
    max_profit = np.max(pnls)
    
    # Percentiles
    p5 = np.percentile(pnls, 5)
    p95 = np.percentile(pnls, 95)
    
    # Generate histogram data for the UI
    hist, bin_edges = np.histogram(pnls, bins=50)
    histogram = [{"bin_start": float(bin_edges[i]), "bin_end": float(bin_edges[i+1]), "count": int(hist[i])} for i in range(len(hist))]
    
    return {
        "expected_value": float(expected_value),
        "prob_profit": float(prob_profit),
        "max_loss": float(max_loss),
        "max_profit": float(max_profit),
        "confidence_interval_90": [float(p5), float(p95)],
        "histogram": histogram
    }
