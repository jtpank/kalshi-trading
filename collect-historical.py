import os
import csv
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization

from KalshiClients.KalshiClients import KalshiHttpClient, KalshiEnvironment
from pathlib import Path
import pandas as pd


load_dotenv()

ENV = KalshiEnvironment.PROD
KEYID = os.getenv("PROD_KEYID")
KEYFILE = os.getenv("PROD_KEYFILE")


def load_client() -> KalshiHttpClient:
    if not KEYID or not KEYFILE:
        raise RuntimeError("Missing PROD_KEYID or PROD_KEYFILE in .env")

    with open(KEYFILE, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None,
        )

    return KalshiHttpClient(
        key_id=KEYID,
        private_key=private_key,
        environment=ENV,
    )


def iso_to_ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def ts_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def get_market(client: KalshiHttpClient, ticker: str) -> dict[str, Any]:
    resp = client.get(f"/trade-api/v2/markets/{ticker}")
    market = resp.get("market")
    if not market:
        raise RuntimeError(f"Could not retrieve market for ticker={ticker}")
    return market


def fetch_all_trades_from_endpoint(
    client: KalshiHttpClient,
    path: str,
    ticker: str,
    min_ts: int | None = None,
    max_ts: int | None = None,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        params: dict[str, Any] = {
            "ticker": ticker,
            "limit": 1000,
        }

        if min_ts is not None:
            params["min_ts"] = min_ts
        if max_ts is not None:
            params["max_ts"] = max_ts
        if cursor:
            params["cursor"] = cursor

        resp = client.get(path, params=params)
        batch = resp.get("trades", [])
        trades.extend(batch)

        cursor = resp.get("cursor")
        if not cursor:
            break

    return trades


def fetch_all_trades_with_fallback(
    client: KalshiHttpClient,
    ticker: str,
    min_ts: int | None = None,
    max_ts: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    historical_path = "/trade-api/v2/historical/trades"
    live_path = "/trade-api/v2/markets/trades"

    historical_trades = fetch_all_trades_from_endpoint(
        client=client,
        path=historical_path,
        ticker=ticker,
        min_ts=min_ts,
        max_ts=max_ts,
    )
    if historical_trades:
        return historical_trades, "historical"

    live_trades = fetch_all_trades_from_endpoint(
        client=client,
        path=live_path,
        ticker=ticker,
        min_ts=min_ts,
        max_ts=max_ts,
    )
    return live_trades, "live"


def normalize_trade(trade: dict[str, Any], fallback_ticker: str) -> dict[str, Any]:
    created_time = trade["created_time"]
    ts = iso_to_ts(created_time)

    yes_price_raw = trade.get("yes_price_dollars")
    no_price_raw = trade.get("no_price_dollars")
    count_raw = trade.get("count_fp")

    return {
        "trade_id": trade.get("trade_id"),
        "ticker": trade.get("ticker", fallback_ticker),
        "created_time": created_time,
        "ts": ts,
        "yes_price_dollars": float(yes_price_raw) if yes_price_raw is not None else None,
        "no_price_dollars": float(no_price_raw) if no_price_raw is not None else None,
        "count_fp": float(count_raw) if count_raw is not None else None,
        "taker_side": trade.get("taker_side"),
    }


def write_raw_trades_csv(trades: list[dict[str, Any]], output_file: str) -> None:
    fieldnames = [
        "trade_id",
        "ticker",
        "created_time",
        "ts",
        "yes_price_dollars",
        "no_price_dollars",
        "count_fp",
        "taker_side",
    ]

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trades)


def build_second_ohlc(
    trades: list[dict[str, Any]],
    start_ts: int,
    end_ts: int,
) -> list[dict[str, Any]]:
    if start_ts > end_ts:
        raise ValueError("start_ts must be <= end_ts")

    trades_sorted = sorted(trades, key=lambda x: (x["ts"], x["trade_id"] or ""))

    by_second: dict[int, list[dict[str, Any]]] = {}
    for t in trades_sorted:
        sec = t["ts"]
        if start_ts <= sec <= end_ts:
            by_second.setdefault(sec, []).append(t)

    rows: list[dict[str, Any]] = []
    prev_close: float | None = None

    for sec in range(start_ts, end_ts + 1):
        second_trades = by_second.get(sec, [])

        if second_trades:
            prices = [
                t["yes_price_dollars"]
                for t in second_trades
                if t["yes_price_dollars"] is not None
            ]

            if prices:
                open_px = prices[0]
                high_px = max(prices)
                low_px = min(prices)
                close_px = prices[-1]
                volume = sum((t["count_fp"] or 0.0) for t in second_trades)
                num_trades = len(prices)
                prev_close = close_px
            else:
                open_px = high_px = low_px = close_px = prev_close
                volume = 0.0
                num_trades = 0
        else:
            open_px = high_px = low_px = close_px = prev_close
            volume = 0.0
            num_trades = 0

        rows.append(
            {
                "ts": sec,
                "time": ts_to_iso(sec),
                "open_yes_price_dollars": open_px,
                "high_yes_price_dollars": high_px,
                "low_yes_price_dollars": low_px,
                "close_yes_price_dollars": close_px,
                "volume_contracts": volume,
                "num_trades": num_trades,
            }
        )

    return rows


def write_second_ohlc_csv(rows: list[dict[str, Any]], output_file: str) -> None:
    fieldnames = [
        "ts",
        "time",
        "open_yes_price_dollars",
        "high_yes_price_dollars",
        "low_yes_price_dollars",
        "close_yes_price_dollars",
        "volume_contracts",
        "num_trades",
    ]

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def load_tickers(path: str) -> list[str]:
    with open(path, "r") as f:
        return [line.strip() for line in f if line.strip()]

def main() -> None:
    client = load_client()

    # Change this ticker as needed
    # ticker = "KXNBAGAME-26APR09LALGSW-GSW"
    tickers = load_tickers("tickers.txt")
    for ticker in tickers:
        print(f"Fetching market for {ticker}...")
        market = get_market(client, ticker)

        print("\n=== MARKET ===")
        print(
            {
                "ticker": market.get("ticker"),
                "title": market.get("title"),
                "status": market.get("status"),
                "open_time": market.get("open_time"),
                "close_time": market.get("close_time"),
            }
        )

        open_time = market.get("open_time")
        close_time = market.get("close_time")
        if not open_time or not close_time:
            raise RuntimeError("Market missing open_time or close_time")

        min_ts = iso_to_ts(open_time)
        max_ts = iso_to_ts(close_time)

        print(f"\nFetching trades between {open_time} and {close_time}...")
        raw_trades, source = fetch_all_trades_with_fallback(
            client=client,
            ticker=ticker,
            min_ts=min_ts,
            max_ts=max_ts,
        )

        print(f"Fetched {len(raw_trades)} trades from source={source}")

        normalized_trades = [normalize_trade(t, ticker) for t in raw_trades]
        normalized_trades.sort(key=lambda x: (x["ts"], x["trade_id"] or ""))

        raw_csv = f"output_data/live_raw_trades/{ticker}_{source}_raw_trades.csv"
        write_raw_trades_csv(normalized_trades, raw_csv)
        print(f"Wrote raw trades to {raw_csv}")

        if not normalized_trades:
            print("No trades found for this market in the requested window.")
            return

        ohlc_rows = build_second_ohlc(
            trades=normalized_trades,
            start_ts=min_ts,
            end_ts=max_ts,
        )

        ohlc_csv = f"output_data/{ticker}_{source}_1s_ohlc.csv"
        write_second_ohlc_csv(ohlc_rows, ohlc_csv)
        print(f"Wrote 1-second OHLC to {ohlc_csv}")

def process_historical_csv():
    tickers = load_tickers("tickers.txt")
    window_seconds = 3 * 60 * 60  # 3 hours

    for ticker in tickers:
        print(f"Processing {ticker}...")
        csv_file = Path(f"output_data/{ticker}_live_1s_ohlc.csv")

        if not csv_file.exists():
            print(f"Skipping {csv_file.name}: file does not exist")
            continue

        try:
            df = pd.read_csv(csv_file)
        except Exception as e:
            print(f"Skipping {csv_file.name}: read_csv failed: {e}")
            continue

        if "ts" not in df.columns:
            print(f"Skipping {csv_file.name}: no 'ts' column")
            continue

        if "open_yes_price_dollars" not in df.columns:
            print(f"Skipping {csv_file.name}: no 'open_yes_price_dollars' column")
            continue

        df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
        df = df.dropna(subset=["ts"]).copy()

        if df.empty:
            print(f"Skipping {csv_file.name}: no valid ts rows")
            continue

        df["ts"] = df["ts"].astype(int)

        last_ts = df["ts"].iloc[-1]
        cutoff_ts = last_ts - window_seconds
        filtered_df = df[df["ts"] >= cutoff_ts].copy()

        if filtered_df.empty:
            print(f"Skipping {csv_file.name}: no rows in 3-hour window")
            continue

        first_open = pd.to_numeric(
            filtered_df.iloc[0]["open_yes_price_dollars"],
            errors="coerce"
        )

        if pd.isna(first_open):
            print(f"Skipping {csv_file.name}: first filtered open_yes_price_dollars is NaN")
            continue

        if first_open < 0.5:
            output_dir = Path("output_data/pregame_underdogs")
        else:
            output_dir = Path("output_data/pregame_favorites")

        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / csv_file.name

        try:
            filtered_df.to_csv(output_file, index=False)
        except Exception as e:
            print(f"Skipping {csv_file.name}: failed to write output: {e}")
            continue

        print(
            f"{csv_file.name}: last_ts={last_ts}, cutoff_ts={cutoff_ts}, "
            f"first_open={first_open}, kept {len(filtered_df)}/{len(df)} rows -> {output_file}"
        )

    # INPUT_DIR = Path("input_csvs")
    # OUTPUT_DIR = Path("filtered_csvs")
    # WINDOW_SECONDS = 3 * 60 * 60  # 3 hours

    # OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # for csv_file in INPUT_DIR.glob("*.csv"):
    #     df = pd.read_csv(csv_file)

    #     if "ts" not in df.columns:
    #         print(f"Skipping {csv_file.name}: no 'ts' column")
    #         continue

    #     # make ts numeric in case of blanks/strings
    #     df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
    #     df = df.dropna(subset=["ts"]).copy()

    #     if df.empty:
    #         print(f"Skipping {csv_file.name}: no valid ts rows")
    #         continue

    #     df["ts"] = df["ts"].astype(int)

    #     last_ts = df["ts"].iloc[-1]
    #     cutoff_ts = last_ts - WINDOW_SECONDS

    #     filtered_df = df[df["ts"] >= cutoff_ts].copy()

    #     output_file = OUTPUT_DIR / csv_file.name
    #     filtered_df.to_csv(output_file, index=False)

    #     print(
    #         f"{csv_file.name}: last_ts={last_ts}, cutoff_ts={cutoff_ts}, "
    #         f"kept {len(filtered_df)}/{len(df)} rows -> {output_file}"
    #     )

if __name__ == "__main__":
    # process_historical_csv()
    pass