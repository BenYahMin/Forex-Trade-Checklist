import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime

# ---------------------------
# User settings
# ---------------------------
SYMBOL = "EURUSD"
REFRESH_SECONDS = 60

TIMEFRAMES = {
    "Weekly": mt5.TIMEFRAME_W1,
    "Daily": mt5.TIMEFRAME_D1,
    "4H": mt5.TIMEFRAME_H4,
    "1H": mt5.TIMEFRAME_H1,
    "15M": mt5.TIMEFRAME_M15
}

# Indicator settings
RSI_PERIOD = 14
EMA_FAST = 20
EMA_SLOW = 50
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ADX_PERIOD = 14

# ---------------------------
# MT5 init
# ---------------------------
if not mt5.initialize():
    print("Failed to initialize MT5. Make sure MetaTrader 5 is installed and a broker is running.")
    mt5.shutdown()
    raise SystemExit

# ---------------------------
# Helpers (adapted from your functions)
# ---------------------------

def get_candles(symbol, timeframe, n=300):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if rates is None:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def market_structure(df):
    closes = df["close"].iloc[-10:]

    if closes.iloc[-1] > closes.max():
        return "Bullish", 100
    if closes.iloc[-1] < closes.min():
        return "Bearish", 100

    if closes.iloc[-1] > closes.iloc[-3]:
        return "Bullish", 70
    if closes.iloc[-1] < closes.iloc[-3]:
        return "Bearish", 70

    return "Neutral", 40


def calculate_adx(df, period=ADX_PERIOD):
    df = df.copy()
    df["H-L"] = df["high"] - df["low"]
    df["H-PC"] = (df["high"] - df["close"].shift(1)).abs()
    df["L-PC"] = (df["low"] - df["close"].shift(1)).abs()
    df["TR"] = df[["H-L", "H-PC", "L-PC"]].max(axis=1)

    df["+DM"] = np.where(df["high"] > df["high"].shift(1), df["high"] - df["high"].shift(1), 0)
    df["-DM"] = np.where(df["low"] < df["low"].shift(1), df["low"].shift(1) - df["low"], 0)

    df["+DM"] = np.where(df["+DM"] > df["-DM"], df["+DM"], 0)
    df["-DM"] = np.where(df["-DM"] > df["+DM"], df["-DM"], 0)

    df["TR14"] = df["TR"].rolling(period).sum()
    df["+DM14"] = df["+DM"].rolling(period).sum()
    df["-DM14"] = df["-DM"].rolling(period).sum()

    df["+DI"] = 100 * (df["+DM14"] / df["TR14"])
    df["-DI"] = 100 * (df["-DM14"] / df["TR14"])

    df["DX"] = 100 * (df["+DI"] - df["-DI"]).abs() / (df["+DI"] + df["-DI"])
    adx = df["DX"].rolling(period).mean()

    return adx.iloc[-1]


def calculate_trend(df):
    df = df.copy()
    df["EMA_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()

    ema_direction = 100 if df["EMA_fast"].iloc[-1] > df["EMA_slow"].iloc[-1] else 0

    adx_value = calculate_adx(df)
    if adx_value >= 25:
        adx_score = 100
    elif 20 <= adx_value < 25:
        adx_score = 60
    else:
        adx_score = 30

    struct_dir, struct_score = market_structure(df)

    slope = df["EMA_fast"].iloc[-1] - df["EMA_fast"].iloc[-5]
    momentum_score = 100 if slope > 0 else 50

    trend_percentage = round(
        (ema_direction * 0.4) +
        (adx_score * 0.25) +
        (struct_score * 0.25) +
        (momentum_score * 0.10)
    )

    direction = "Bullish" if trend_percentage >= 50 else "Bearish"
    return direction, trend_percentage


def calculate_rsi(df):
    delta = df["close"].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(RSI_PERIOD).mean()
    avg_loss = pd.Series(loss).rolling(RSI_PERIOD).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    latest = rsi.iloc[-1]

    if 40 <= latest <= 70:
        rsi_pct = 90
    elif 30 <= latest < 40:
        rsi_pct = 60
    elif latest < 30:
        rsi_pct = 30
    else:
        rsi_pct = 20

    alignment = "Supports Trade" if rsi_pct >= 50 else "Opposes Trade"
    return latest, rsi_pct, alignment


def calculate_macd(df):
    ema_fast_calc = df["close"].ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow_calc = df["close"].ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast_calc - ema_slow_calc
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist = macd_line - signal_line

    if macd_line.iloc[-1] > signal_line.iloc[-1] and hist.iloc[-1] > 0:
        macd_pct = 90
    elif macd_line.iloc[-1] > signal_line.iloc[-1]:
        macd_pct = 70
    elif macd_line.iloc[-1] < signal_line.iloc[-1] and hist.iloc[-1] < 0:
        macd_pct = 20
    else:
        macd_pct = 40

    alignment = "Supports Trade" if macd_pct >= 50 else "Opposes Trade"
    return macd_line.iloc[-1], hist.iloc[-1], macd_pct, alignment


# ---------------------------
# GUI
# ---------------------------
class ForexChecklistGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Forex Checklist — {SYMBOL}")
        self.root.geometry("980x300")

        # Header
        header = tk.Label(root, text=f"Live Forex Checklist — {SYMBOL}", font=("Helvetica", 16, "bold"))
        header.pack(pady=6)

        # Table frame
        frame = tk.Frame(root)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        cols = ["Timeframe", "Trend", "Trend %", "RSI", "RSI %", "MACD", "MACD %"]

        # Column headers
        for c, col in enumerate(cols):
            lbl = tk.Label(frame, text=col, font=("Helvetica", 10, "bold"), borderwidth=1, relief="ridge", padx=6, pady=6)
            lbl.grid(row=0, column=c, sticky="nsew")
            frame.grid_columnconfigure(c, weight=1)

        # Data labels per timeframe
        self.cells = {}
        for r, tf in enumerate(TIMEFRAMES.keys(), start=1):
            tf_lbl = tk.Label(frame, text=tf, font=("Helvetica", 10), borderwidth=1, relief="ridge", padx=6, pady=6)
            tf_lbl.grid(row=r, column=0, sticky="nsew")
            self.cells[tf] = {}
            for c in range(1, len(cols)):
                lbl = tk.Label(frame, text="-", font=("Helvetica", 10), borderwidth=1, relief="ridge", padx=6, pady=6)
                lbl.grid(row=r, column=c, sticky="nsew")
                self.cells[tf][cols[c]] = lbl

        # Footer / status
        self.status = tk.Label(root, text="Last update: never", anchor="w")
        self.status.pack(fill=tk.X, padx=8, pady=(0,6))

        # start updating
        self.update_all()

    def color_for_pct(self, pct):
        # simple mapping
        if pct >= 70:
            return "#b7f0c6"  # light green
        if 50 <= pct < 70:
            return "#fff2b2"  # light yellow
        return "#ffc6c6"      # light red

    def update_all(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for tf_name, tf_code in TIMEFRAMES.items():
            df = get_candles(SYMBOL, tf_code)
            if df is None or len(df) < 60:
                # mark unavailable
                for lbl in self.cells[tf_name].values():
                    lbl.config(text="N/A", bg="lightgrey")
                continue

            # Trend
            try:
                direction, trend_pct = calculate_trend(df)
            except Exception as e:
                direction, trend_pct = "Err", 0

            # RSI
            try:
                rsi_val, rsi_pct, rsi_align = calculate_rsi(df)
            except Exception as e:
                rsi_val, rsi_pct, rsi_align = (0, 0, "Err")

            # MACD
            try:
                macd_val, hist, macd_pct, macd_align = calculate_macd(df)
            except Exception as e:
                macd_val, hist, macd_pct, macd_align = (0, 0, 0, "Err")

            # Update GUI
            self.cells[tf_name]["Trend"].config(text=f"{direction}")
            self.cells[tf_name]["Trend %"].config(text=f"{trend_pct}%", bg=self.color_for_pct(trend_pct))

            self.cells[tf_name]["RSI"].config(text=f"{round(rsi_val,2)}")
            self.cells[tf_name]["RSI %"].config(text=f"{rsi_pct}%", bg=self.color_for_pct(rsi_pct))

            self.cells[tf_name]["MACD"].config(text=f"{round(macd_val,6)}")
            self.cells[tf_name]["MACD %"].config(text=f"{macd_pct}%", bg=self.color_for_pct(macd_pct))

        self.status.config(text=f"Last update: {now} — refreshing every {REFRESH_SECONDS}s")
        # schedule next update
        self.root.after(REFRESH_SECONDS * 1000, self.update_all)


if __name__ == "__main__":
    root = tk.Tk()
    app = ForexChecklistGUI(root)
    try:
        root.mainloop()
    finally:
        mt5.shutdown()
