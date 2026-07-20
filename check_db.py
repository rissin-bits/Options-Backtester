import sqlite3
import os
from confignew import STATE_DB_PATH

db_path = STATE_DB_PATH
if not os.path.exists(db_path):
    print("Database not found!")
    exit(1)

db = sqlite3.connect(db_path)
print('Done:', db.execute("select count(*) from contracts where status='done'").fetchone()[0])
print('Empty:', db.execute("select count(*) from contracts where status='empty'").fetchone()[0])
print('Error:', db.execute("select count(*) from contracts where status='error'").fetchone()[0])
print('Pending:', db.execute("select count(*) from contracts where status='pending'").fetchone()[0])
