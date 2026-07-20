import sqlite3
db = sqlite3.connect(r'C:\OptionsData\upstox_backfill_state.db')
cursor = db.execute("SELECT last_error, COUNT(*) FROM contracts WHERE status='error' GROUP BY last_error")
print("Errors:", cursor.fetchall())
db.close()
