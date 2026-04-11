from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def load_tickers(path: str) -> list[str]:
    with open(path, "r") as f:
        return [line.strip() for line in f if line.strip()]


def build_chart(csv_path: Path, output_dir: Path) -> None:
    df = pd.read_csv(csv_path)

    required_cols = [
        "time",
        "open_yes_price_dollars",
        "high_yes_price_dollars",
        "low_yes_price_dollars",
        "close_yes_price_dollars",
        "num_trades",
        "volume_contracts",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"{csv_path}: missing required columns: {missing}")

    df["time"] = pd.to_datetime(df["time"], utc=True)

    for col in [
        "open_yes_price_dollars",
        "high_yes_price_dollars",
        "low_yes_price_dollars",
        "close_yes_price_dollars",
        "num_trades",
        "volume_contracts",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    ohlc_mask = df[
        [
            "open_yes_price_dollars",
            "high_yes_price_dollars",
            "low_yes_price_dollars",
            "close_yes_price_dollars",
        ]
    ].notna().all(axis=1)

    df = df.loc[ohlc_mask].copy()

    if df.empty:
        print(f"Skipping {csv_path.name}: no valid OHLC rows found.")
        return

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.75, 0.25],
        subplot_titles=("YES Price Candles", "Number of Trades"),
    )

    fig.add_trace(
        go.Candlestick(
            x=df["time"],
            open=df["open_yes_price_dollars"],
            high=df["high_yes_price_dollars"],
            low=df["low_yes_price_dollars"],
            close=df["close_yes_price_dollars"],
            name="YES Price",
            customdata=df[["num_trades", "volume_contracts"]].to_numpy(),
            hovertemplate=(
                "Time: %{x}<br>"
                "Open: %{open:.4f}<br>"
                "High: %{high:.4f}<br>"
                "Low: %{low:.4f}<br>"
                "Close: %{close:.4f}<br>"
                "Num Trades: %{customdata[0]}<br>"
                "Volume Contracts: %{customdata[1]:.2f}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=df["time"],
            y=df["num_trades"],
            name="Num Trades",
            hovertemplate="Time: %{x}<br>Num Trades: %{y}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        title=f"Kalshi 1s OHLC: {csv_path.name}",
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        template="plotly_white",
        height=900,
    )

    fig.update_yaxes(title_text="YES Price", row=1, col=1)
    fig.update_yaxes(title_text="Num Trades", row=2, col=1)
    fig.update_xaxes(title_text="Time", row=2, col=1)

    output_path = output_dir / f"{csv_path.stem}.html"
    fig.write_html(str(output_path), include_plotlyjs=True)
    print(f"Saved interactive chart to {output_path}")


def main() -> None:
    tickers = load_tickers("tickers.txt")

    input_dir = Path("output_data")
    output_dir = input_dir / "output_charts_html"
    output_dir.mkdir(parents=True, exist_ok=True)

    for ticker in tickers:
        csv_path = input_dir / f"{ticker}_live_1s_ohlc.csv"

        if not csv_path.exists():
            print(f"Missing file, skipping: {csv_path}")
            continue

        print(f"Processing {csv_path}...")
        try:
            build_chart(csv_path, output_dir)
        except Exception as e:
            print(f"Failed for {csv_path.name}: {e}")


if __name__ == "__main__":
    main()