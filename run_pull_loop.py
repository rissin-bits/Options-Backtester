"""
run_pull_loop.py — Resilient wrapper for upstox_pull_candles.py

Keeps re-launching the pull script until all contracts are done.
If the pull script crashes (network errors, socket exhaustion, etc.)
this wrapper waits 60s and relaunches — picking up exactly where it left off
thanks to the state DB.
"""
import os
import sys
import time
import subprocess
import sqlite3

from confignew import STATE_DB_PATH

db_path = STATE_DB_PATH
underlyings = 'NIFTY,BANKNIFTY,SENSEX'

def get_counts():
    if not os.path.exists(db_path):
        return 0, 0, 0, 0
    try:
        db = sqlite3.connect(db_path)
        pending = db.execute("select count(*) from contracts where status='pending'").fetchone()[0]
        error = db.execute("select count(*) from contracts where status='error'").fetchone()[0]
        done = db.execute("select count(*) from contracts where status='done'").fetchone()[0]
        empty = db.execute("select count(*) from contracts where status='empty'").fetchone()[0]
        db.close()
        return pending, error, done, empty
    except Exception as e:
        print(f"DB Error: {e}")
        return 0, 0, 0, 0

iteration = 0
while True:
    iteration += 1
    pending, error, done, empty = get_counts()
    total = pending + error + done + empty
    print(f"\n{'='*60}")
    print(f"ITERATION {iteration} | Done: {done} | Empty: {empty} | Error: {error} | Pending: {pending} | Total: {total}")
    print(f"{'='*60}")
    
    if pending == 0 and error == 0:
        print("ALL DOWNLOADS COMPLETED SUCCESSFULLY!")
        break

    # Run pending contracts
    if pending > 0:
        print(f"Pulling {pending} pending contracts...")
        try:
            result = subprocess.run(
                [sys.executable, 'upstox_pull_candles.py', '--underlyings', underlyings, '--interval', '1minute'],
                timeout=7200  # 2hr timeout per run
            )
            print(f"Pull script exited with code {result.returncode}")
        except subprocess.TimeoutExpired:
            print("Pull script timed out after 2 hours. Continuing to next iteration...")

    # Recheck
    pending, error, done, empty = get_counts()

    # Retry errors
    if error > 0 and pending == 0:
        print(f"Retrying {error} errored contracts...")
        # First reset errors back to pending so they get picked up
        db = sqlite3.connect(db_path)
        db.execute("UPDATE contracts SET status='pending' WHERE status='error'")
        db.commit()
        db.close()
        print("Reset errors to pending. Will re-pull on next iteration.")

    # Cooldown between iterations
    print("Cooling down for 60 seconds...")
    time.sleep(60)
