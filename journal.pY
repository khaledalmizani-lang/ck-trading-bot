import sqlite3
import json
import os
import threading
from datetime import datetime
import config

DB_FILE = 'trading_bot.db'
_lock = threading.Lock()

def _migrate_json_to_sqlite():
    if os.path.exists(config.HISTORY_FILE):
        print("[MIGRATION] Found history.json, migrating...")
        try:
            with open(config.HISTORY_FILE, "r") as f:
                data = json.load(f)
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            for entry in data:
                c.execute("INSERT OR IGNORE INTO trades (id, data) VALUES (?, ?)", (entry["id"], json.dumps(entry)))
            conn.commit()
            conn.close()
            os.rename(config.HISTORY_FILE, config.HISTORY_FILE + ".bak")
        except:
            pass

def _init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, data TEXT)''')
    conn.commit()
    conn.close()
    _migrate_json_to_sqlite()

_init_db()

def load_history():
    with _lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT data FROM trades")
        rows = c.fetchall()
        conn.close()
        return [json.loads(row[0]) for row in rows]

def log_signal(signal, price, rsi, volume, symbol=None, sl_price=None, tp_price=None):
    sl_mult = config.STOP_LOSS_PCT / 100
    tp_mult = config.TAKE_PROFIT_PCT / 100
    if sl_price is None:
        stop_loss = round(price * (1 - sl_mult), 6) if signal == "BUY" else round(price * (1 + sl_mult), 6)
        take_profit = round(price * (1 + tp_mult), 6) if signal == "BUY" else round(price * (1 - tp_mult), 6)
    else:
        stop_loss, take_profit = sl_price, tp_price

    with _lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT MAX(id) FROM trades")
        row = c.fetchone()
        entry_id = (row[0] + 1) if row[0] is not None else 0
        entry = {"id": entry_id, "timestamp": datetime.now().isoformat(), "symbol": symbol or config.SYMBOL, "signal": signal, "price": price, "rsi": rsi, "volume": volume, "stop_loss": stop_loss, "take_profit": take_profit, "outcome": "PENDING", "exit_reason": "PENDING", "outcome_price": None, "outcome_timestamp": None}
        c.execute("INSERT INTO trades (id, data) VALUES (?, ?)", (entry_id, json.dumps(entry)))
        conn.commit()
        conn.close()
    return {"id": entry_id, "stop_loss": stop_loss, "take_profit": take_profit}

def close_trade(entry_id, current_price, exit_reason):
    with _lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT data FROM trades WHERE id = ?", (entry_id,))
        row = c.fetchone()
        if not row: return "ALREADY_CLOSED"
        entry = json.loads(row[0])
        if entry["exit_reason"] != "PENDING": return "ALREADY_CLOSED"
        outcome = "SUCCESS" if (exit_reason == "TAKE_PROFIT" or (entry["signal"]=="BUY" and current_price > entry["price"]) or (entry["signal"]=="SELL" and current_price < entry["price"])) else "FAILURE"
        entry["outcome"] = outcome
        entry["exit_reason"] = exit_reason
        entry["outcome_price"] = current_price
        entry["outcome_timestamp"] = datetime.now().isoformat()
        c.execute("UPDATE trades SET data = ? WHERE id = ?", (json.dumps(entry), entry_id))
        conn.commit()
        conn.close()
    return outcome

def get_pending_trades():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT data FROM trades WHERE data LIKE '%PENDING%'")
    rows = c.fetchall()
    conn.close()
    return [json.loads(r[0]) for r in rows]
