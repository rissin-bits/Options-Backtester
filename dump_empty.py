import sqlite3
from confignew import STATE_DB_PATH

db = sqlite3.connect(STATE_DB_PATH)
rows = db.execute("select underlying, expiry, strike, option_type from contracts where status='empty' order by underlying, expiry, strike limit 1000").fetchall()

artifact_path = 'empty_contracts.md'
with open(artifact_path, 'w') as f:
    f.write('# Unavailable Contracts (No Data)\n\n')
    f.write('These contracts returned empty from the API (usually meaning they were deeply out-of-the-money and had 0 traded volume on the exchange, so no 1-minute candles were formed).\n\n')
    f.write('| Underlying | Expiry | Strike | Type |\n')
    f.write('|---|---|---|---|\n')
    for r in rows:
        f.write(f'| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n')
