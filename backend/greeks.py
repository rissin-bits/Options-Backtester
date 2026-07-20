"""
greeks.py — Vectorized Black-Scholes pricing and Greeks engine using py_vollib.
"""
import numpy as np
import logging

try:
    import py_vollib.black_scholes.implied_volatility as iv
    import py_vollib.black_scholes.greeks.analytical as greeks
    import py_vollib.black_scholes as bs
except ImportError:
    logging.error("py_vollib is not installed. Please run: pip install py_vollib")

def black_scholes(flag: str, S: float, K: float, T: float, r: float, sigma: float):
    """
    Calculate Option Price and Greeks using py_vollib.
    
    flag: 'c' or 'p'
    S: Spot Price
    K: Strike Price
    T: Time to Expiration (in years)
    r: Risk-free rate
    sigma: Volatility
    """
    T = max(T, 1e-6)
    flag = flag.lower()[0]
    
    try:
        price = bs.black_scholes(flag, S, K, T, r, sigma)
        delta = greeks.delta(flag, S, K, T, r, sigma)
        gamma = greeks.gamma(flag, S, K, T, r, sigma)
        theta = greeks.theta(flag, S, K, T, r, sigma) / 365.0  # Convert to per day
        vega = greeks.vega(flag, S, K, T, r, sigma) * 0.01     # Convert to per 1% change
        rho = greeks.rho(flag, S, K, T, r, sigma) * 0.01       # Convert to per 1% change
        
        return {
            "price": price,
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "rho": rho
        }
    except Exception as e:
        logging.debug(f"Error calculating Greeks: {e}")
        return {
            "price": np.nan, "delta": np.nan, "gamma": np.nan,
            "theta": np.nan, "vega": np.nan, "rho": np.nan
        }

def implied_volatility(flag: str, target_price: float, S: float, K: float, T: float, r: float, 
                      max_iter: int = 100, tol: float = 1e-5):
    """
    Calculate Implied Volatility using py_vollib's robust Let's Be Rational algorithm.
    """
    T = max(T, 1e-6)
    flag = flag.lower()[0]
    
    try:
        # py_vollib uses 'c' or 'p'
        sigma = iv.implied_volatility(target_price, S, K, T, r, flag)
        return sigma
    except Exception as e:
        logging.debug(f"Error calculating IV: {e}")
        return np.nan
