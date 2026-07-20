import sqlite3

db = sqlite3.connect(r'C:\OptionsData\upstox_backfill_state.db')
db.execute("UPDATE contracts SET status='pending' WHERE status='error'")
db.commit()
print("Reset successful")
