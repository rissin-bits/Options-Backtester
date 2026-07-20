"""
Manual connectivity check for the Upstox expired-instrument API.

Not a pytest test despite the name — pytest.ini restricts collection to tests/.
Run directly:  python test_upstox_token.py
"""
import upstox_client
from upstox_client.rest import ApiException

# Read the token from upstox_token.txt (gitignored) or UPSTOX_ACCESS_TOKEN.
# It used to be hardcoded here; the Analytics token is valid for a year, so
# committing it would have handed anyone with repo access a live broker
# credential. Never inline it again.
from upstox_auth import get_upstox_client

api_client = get_upstox_client()
expired_api = upstox_client.ExpiredInstrumentApi(api_client)

# Test NIFTY option expired before Oct 2024 (e.g. 26 Sep 2024)
def test_fetch(underlying, underlying_key, expiry_limit):
    try:
        print(f"Fetching expiries for {underlying} ({underlying_key})")
        resp = expired_api.get_expiries(underlying_key)
        expiries = resp.data if resp and resp.data else []
        
        # Filter expiries before expiry_limit
        old_expiries = [e for e in expiries if e < expiry_limit]
        if not old_expiries:
            print(f"No expiries found before {expiry_limit}")
            return
            
        target_expiry = old_expiries[-1] # pick the latest one before the limit
        print(f"Targeting expiry {target_expiry}")
        
        contracts_resp = expired_api.get_expired_option_contracts(
            instrument_key=underlying_key,
            expiry_date=target_expiry
        )
        contracts = contracts_resp.data if contracts_resp and contracts_resp.data else []
        
        if not contracts:
            print(f"No contracts found for {target_expiry}")
            return
            
        c = contracts[len(contracts)//2]
        exp_key = f"{c.segment}|{c.exchange_token}" # Upstox API v2 expired format may just be segment|exchange_token or whatever the get_expired_historical_candle_data needs, let's use the one from enumerate:
        exp_key = f"{c.segment}|{c.exchange_token}|{target_expiry[8:10]}-{target_expiry[5:7]}-{target_expiry[0:4]}" # Wait, in upstox_enumerate_contracts they use this format, but for historical candle, wait, what format is used? The DB stores it. But the historical candle API might just take the instrument_key if the string is returned. Actually, let's just pass `c.instrument_key` if it exists.
        # Actually in upstox_enumerate_contracts.py:
        # exp_key = f"{c.segment}|{c.exchange_token}|{expiry_str[8:10]}-{expiry_str[5:7]}-{expiry_str[0:4]}"
        # wait no, let's just use the `instrument_key` attribute if present.
        # let's try the manually constructed one first
        
        strike = getattr(c, "strike_price", 0)
        opt_type = getattr(c, "instrument_type", "CE")
        print(f"Testing {underlying} - {target_expiry} - {strike} {opt_type} ({exp_key})")
        
        resp2 = expired_api.get_expired_historical_candle_data(
            expired_instrument_key=exp_key,
            interval="1minute",
            to_date=target_expiry,
            from_date="2022-01-01"
        )
        if resp2 and resp2.data and resp2.data.candles:
            print(f"Success! Fetched {len(resp2.data.candles)} candles.")
            print(f"First candle: {resp2.data.candles[-1]}")
            print(f"Last candle: {resp2.data.candles[0]}")
        else:
            print("No data returned but API call succeeded.")
            
    except ApiException as e:
        print(f"API Exception for {underlying}: {e.status} {e.reason} - {e.body}")
    except Exception as e:
        print(f"Exception for {underlying}: {e}")

test_fetch("NIFTY", "NSE_INDEX|Nifty 50", "2024-10-01")
test_fetch("BANKNIFTY", "NSE_INDEX|Nifty Bank", "2024-10-01")
test_fetch("SENSEX", "BSE_INDEX|SENSEX", "2024-10-01")
