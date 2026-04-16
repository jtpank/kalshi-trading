from loguru import logger as log
import math
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

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

    def analyze_reversions(self, price_col: str, time_col: str):
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
        t = values[time_col].to_numpy()

        x0 = x[0]
        delta = x - x0

        delta_filtered = np.array([0 if math.fabs(v) < 0.02 else v for v in delta])

        local_mins = []
        local_maxs = []
        cross_neg = []
        cross_pos = []
        last_sign = 0  # -1, 0, +1
        for idx, val in enumerate(delta_filtered[1:], start=1):
            if val > 0:
                curr_sign = 1
            elif val < 0:
                curr_sign = -1
            else:
                curr_sign = 0

            if curr_sign == 0:
                continue

            if last_sign == 1 and curr_sign == -1:
                cross_neg.append(idx)

            if last_sign == -1 and curr_sign == 1:
                cross_pos.append(idx)

            last_sign = curr_sign

        print(f"pos: {len(cross_pos)} neg: {len(cross_neg)}")

        log.info(f"Reference level x0 = {x0:.4f}")
        plt.figure(figsize=(10, 5))
        plt.plot(t, delta_filtered, label="delta = x(t) - x0")
        plt.axhline(0.0, linestyle="--", label="x0 reference")

        if cross_pos:
            plt.scatter(
                t[cross_pos],
                delta_filtered[cross_pos],
                marker="x",
                s=80,
                c="green",
                label="cross_pos",
                zorder=3,
            )

        if cross_neg:
            plt.scatter(
                t[cross_neg],
                delta_filtered[cross_neg],
                marker="x",
                s=80,
                c="red",
                label="cross_neg",
                zorder=3,
            )

        plt.xlabel(time_col)
        plt.ylabel("Delta")
        plt.title(f"delta vs {time_col}")
        plt.legend()
        plt.tight_layout()
        plt.show()

    def run(self):
        log.info("Executing...")
        game = "KXNBAGAME-26APR06DETORL-DET"
        csv_path = Path(f"../output_data/pregame_favorites/{game}_live_1s_ohlc.csv")
        df = self.load_data(csv_path)
        price_col = "open_yes_price_dollars"
        time_col = "time"
        self.analyze_reversions(price_col, time_col)



if __name__=="__main__":
    driver = Analysis()
    driver.run()

