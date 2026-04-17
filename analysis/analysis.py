from loguru import logger as log
import math
from pathlib import Path
import pandas as pd
import numpy as np
from dataclasses import dataclass
@dataclass
class MarketOrder:
    ticker: str
    favored_side: str
    count: int
    limit_price_dollars: float

class Analysis:
    def __init__(self):
        log.info("constructed analysis class")
        self.df = None

    def load_data(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            raise FileNotFoundError(f"{path} not found")

        if path.suffix.lower() != ".csv":
            raise ValueError(f"Expected .csv, got {path.suffix}")

        log.info("Loading data...")
        self.df = pd.read_csv(path)

        if self.df.empty:
            log.warning("Loaded file is empty!")
        else:
            log.info(f"Loaded dataframe with shape {self.df.shape}")
            log.info(f"Columns: {list(self.df.columns)}")
        log.info(self.df.head())

        return self.df

    def analyze_reversions(
        self,
        price_col: str,
        time_col: str,
        epsilon: float = 0.02,
        preterminal_cutoff: float = 10200,
        terminal_cutoff: float = 10800,
    ):
        if self.df is None:
            raise ValueError("Data is not loaded yet")
        if price_col not in self.df.columns:
            raise KeyError(f"Missing column: {price_col}")
        if time_col not in self.df.columns:
            raise KeyError(f"Missing column: {time_col}")

        values = self.df[[time_col, price_col]].copy()
        values = values.dropna(subset=[time_col, price_col]).sort_values(time_col).reset_index(drop=True)

        if values.empty:
            raise ValueError("No usable data after dropping NaNs")

        x = values[price_col].astype(float).to_numpy()
        t = values[time_col].astype(float).to_numpy()
        t = t - t[0]
        x0 = float(x[0])
        delta = x - x0

        def sign_with_band(v: float) -> int:
            if v > epsilon:
                return 1
            if v < -epsilon:
                return -1
            return 0

        delta_filtered = np.array([0.0 if math.fabs(v) < epsilon else v for v in delta])
        signs = np.array([sign_with_band(v) for v in delta])

        # Pre-terminal only
        pre_mask = t < preterminal_cutoff
        pre_idx = np.where(pre_mask)[0]

        if len(pre_idx) == 0:
            raise ValueError("No data before preterminal cutoff")

        cross_pos = []
        cross_neg = []
        excursions = []

        last_sign = 0
        excursion_start_idx = None
        excursion_start_sign = None

        for idx in pre_idx:
            curr_sign = signs[idx]

            if curr_sign == 0:
                continue

            if last_sign == 0:
                last_sign = curr_sign
                excursion_start_idx = idx
                excursion_start_sign = curr_sign
                continue

            if curr_sign != last_sign:
                segment_start = excursion_start_idx
                segment_end = idx

                seg_delta = delta[segment_start:segment_end + 1]
                seg_t = t[segment_start:segment_end + 1]

                peak_delta = float(np.max(seg_delta))
                valley_delta = float(np.min(seg_delta))

                excursion = {
                    "start_idx": int(segment_start),
                    "end_idx": int(segment_end),
                    "start_time": float(seg_t[0]),
                    "end_time": float(seg_t[-1]),
                    "duration": float(seg_t[-1] - seg_t[0]),
                    "start_sign": int(excursion_start_sign),
                    "end_sign": int(curr_sign),
                    "cross_type": "neg_to_pos" if excursion_start_sign == -1 and curr_sign == 1 else "pos_to_neg",
                    "peak_delta": peak_delta,
                    "valley_delta": valley_delta,
                    "peak_abs_price": float(x0 + peak_delta),
                    "valley_abs_price": float(x0 + valley_delta),
                    "amplitude": float(peak_delta - valley_delta),
                    "returned_before_cutoff": True,
                }
                excursions.append(excursion)

                if curr_sign == 1:
                    cross_pos.append(idx)
                else:
                    cross_neg.append(idx)

                excursion_start_idx = idx
                excursion_start_sign = curr_sign
                last_sign = curr_sign

        # Final unfinished pre-terminal excursion
        if excursion_start_idx is not None:
            last_pre_idx = pre_idx[-1]
            if excursion_start_idx < last_pre_idx:
                seg_delta = delta[excursion_start_idx:last_pre_idx + 1]
                seg_t = t[excursion_start_idx:last_pre_idx + 1]

                excursions.append({
                    "start_idx": int(excursion_start_idx),
                    "end_idx": int(last_pre_idx),
                    "start_time": float(seg_t[0]),
                    "end_time": float(seg_t[-1]),
                    "duration": float(seg_t[-1] - seg_t[0]),
                    "start_sign": int(excursion_start_sign),
                    "end_sign": int(excursion_start_sign),
                    "cross_type": "unfinished",
                    "peak_delta": float(np.max(seg_delta)),
                    "valley_delta": float(np.min(seg_delta)),
                    "peak_abs_price": float(x0 + np.max(seg_delta)),
                    "valley_abs_price": float(x0 + np.min(seg_delta)),
                    "amplitude": float(np.max(seg_delta) - np.min(seg_delta)),
                    "returned_before_cutoff": False,
                })

        excursions_df = pd.DataFrame(excursions)

        completed_excursions = (
            excursions_df[excursions_df["cross_type"] != "unfinished"].copy()
            if not excursions_df.empty else pd.DataFrame()
        )

        # Terminal window stats
        term_mask = (t >= preterminal_cutoff) & (t <= terminal_cutoff)
        term_idx = np.where(term_mask)[0]

        terminal_summary = {}
        if len(term_idx) > 0:
            terminal_delta = delta[term_idx]
            terminal_x = x[term_idx]

            terminal_summary = {
                "terminal_start_time": float(t[term_idx[0]]),
                "terminal_end_time": float(t[term_idx[-1]]),
                "terminal_points": int(len(term_idx)),
                "terminal_start_price": float(terminal_x[0]),
                "terminal_end_price": float(terminal_x[-1]),
                "terminal_start_delta": float(terminal_delta[0]),
                "terminal_end_delta": float(terminal_delta[-1]),
                "terminal_max_price": float(np.max(terminal_x)),
                "terminal_min_price": float(np.min(terminal_x)),
                "terminal_mean_price": float(np.mean(terminal_x)),
            }

        summary = {
            "x0": x0,
            "num_points_total": int(len(x)),
            "num_points_preterminal": int(len(pre_idx)),
            "num_cross_pos_preterminal": int(len(cross_pos)),
            "num_cross_neg_preterminal": int(len(cross_neg)),
            "num_cross_total_preterminal": int(len(cross_pos) + len(cross_neg)),
            "num_excursions_total_preterminal": int(len(excursions_df)),
            "num_completed_excursions_preterminal": int(len(completed_excursions)),
            "fraction_excursions_returned_before_cutoff": (
                float(completed_excursions.shape[0] / excursions_df.shape[0])
                if not excursions_df.empty else np.nan
            ),
            "max_peak_delta_preterminal": (
                float(completed_excursions["peak_delta"].max())
                if not completed_excursions.empty else np.nan
            ),
            "max_valley_delta_preterminal": (
                float(completed_excursions["valley_delta"].min())
                if not completed_excursions.empty else np.nan
            ),
            "avg_excursion_duration_preterminal": (
                float(completed_excursions["duration"].mean())
                if not completed_excursions.empty else np.nan
            ),
            "median_excursion_duration_preterminal": (
                float(completed_excursions["duration"].median())
                if not completed_excursions.empty else np.nan
            ),
        }

        summary.update(terminal_summary)

        log.info(f"x0 = {x0:.4f}")
        log.info(f"pre-terminal positive crossovers: {summary['num_cross_pos_preterminal']}")
        log.info(f"pre-terminal negative crossovers: {summary['num_cross_neg_preterminal']}")
        log.info(f"fraction returned before cutoff: {summary['fraction_excursions_returned_before_cutoff']}")

        print("\nSUMMARY")
        for k, v in summary.items():
            print(f"{k}: {v}")

        if not excursions_df.empty:
            print("\nEXCURSIONS")
            print(excursions_df.head(20))

        return summary, excursions_df

    def run(self):
        log.info("Executing...")
        game = "KXNBAGAME-26APR01ATLORL-ATL"
        with open("/home/justin/Desktop/000-github/kalshi-trading/favorites_tickers.txt", "r") as f:
            tickers = [line.strip() for line in f if line.strip()]
        for idx, game in enumerate(tickers):
            csv_path = Path(f"../output_data/pregame_favorites/{game}_live_1s_ohlc.csv")
            df = self.load_data(csv_path)
            price_col = "open_yes_price_dollars"
            time_col = "ts"
            self.analyze_reversions(
                price_col=price_col,
                time_col=time_col,
                epsilon=0.02,
                preterminal_cutoff=9000,
                terminal_cutoff=10800,
            )
            if idx == 10:
                break
fees_per100 = {
    1 : 7,
    5 : 34,
    10 : 63,
    15 : 90,
    20 : 112,
    25 : 132,
    30 : 147,
    35 : 160,
    40 : 168,
    45 : 174,
    50 : 175,
    55 : 174,
    60 : 168,
    65 : 160,
    70 : 147,
    75 : 132,
    80 : 112,
    90 : 90,
    95 : 34,
    99 : 7
}
def compute_fee(order: MarketOrder) -> float:
    hundred_contracts = order.count // 100
    print(f"hundred_contracts: {hundred_contracts}")
    single_contracts = order.count % 100
    print(f"single_contracts: {single_contracts}")
    price = order.limit_price_dollars * 100
    print(f"price: {price}")
    def normalize_price_key(price_cents: float) -> int:
        p = int(round(price))
        if p <= 2:
            return 1
        if p >= 98:
            return 99
        return 5 * round(p / 5)
    
    key = normalize_price_key(price)
    hundreds_fee = (fees_per100[key] * hundred_contracts) / 100.0
    singles_fee = math.ceil(
        0.07 * single_contracts * order.limit_price_dollars * (1 - order.limit_price_dollars) * 100
    ) / 100.0
    print(f"singles fee: {singles_fee:.4f}")
    fees = hundreds_fee + singles_fee
    return fees


if __name__=="__main__":
    # driver = Analysis()
    # driver.run()
    # order = MarketOrder("test", "yes", 1001, 0.13)
    # cost = order.count*order.limit_price_dollars
    # fees = compute_fee(order)
    # print(f"count: {order.count} at {order.limit_price_dollars}")
    # print(f"cost: {cost} fee: {fees} pct: {fees/cost * 100}%")


