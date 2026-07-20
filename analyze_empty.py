import sqlite3
from confignew import STATE_DB_PATH

db = sqlite3.connect(STATE_DB_PATH)

print("=== Empty by underlying ===")
for r in db.execute("select underlying, count(*) from contracts where status='empty' group by underlying").fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n=== Strike range for EMPTY vs DONE (NIFTY, same expiry) ===")
# Pick an expiry that has both done and empty
row = db.execute("select expiry from contracts where status='empty' and underlying='NIFTY' limit 1").fetchone()
if row:
    exp = row[0]
    print(f"\nExpiry: {exp}")
    print("  EMPTY strikes:")
    for r in db.execute("select strike, option_type from contracts where status='empty' and underlying='NIFTY' and expiry=? order by strike", (exp,)).fetchall():
        print(f"    {r[0]} {r[1]}")
    print("  DONE strikes:")
    for r in db.execute("select strike, option_type from contracts where status='done' and underlying='NIFTY' and expiry=? order by strike", (exp,)).fetchall():
        print(f"    {r[0]} {r[1]}")

print("\n=== Strike distance from ATM for empty contracts ===")
# Show min/max strikes for empty vs done
for ul in ['NIFTY', 'BANKNIFTY']:
    empty_strikes = db.execute(f"select min(strike), max(strike), avg(strike) from contracts where status='empty' and underlying=?", (ul,)).fetchone()
    done_strikes = db.execute(f"select min(strike), max(strike), avg(strike) from contracts where status='done' and underlying=?", (ul,)).fetchone()
    print(f"  {ul} EMPTY: min={empty_strikes[0]}, max={empty_strikes[1]}, avg={empty_strikes[2]:.0f}" if empty_strikes[0] else f"  {ul} EMPTY: none")
    print(f"  {ul} DONE:  min={done_strikes[0]}, max={done_strikes[1]}, avg={done_strikes[2]:.0f}" if done_strikes[0] else f"  {ul} DONE: none")

print("\n=== Total counts ===")
for status in ['done', 'empty', 'error', 'pending']:
    c = db.execute(f"select count(*) from contracts where status=?", (status,)).fetchone()[0]
    print(f"  {status}: {c}")
