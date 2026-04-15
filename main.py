
from loguru import logger as log
from traders.LiveTrader import LiveTrader
from traders.SimulatedTrader import SimulatedTrader
from utils.utils import  MarketState,MarketOrder, CurrentStrategyState, KalshiEnvironment, RunType, Portfolio
import os
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization
from KalshiClients.KalshiClients import KalshiHttpClient, KalshiWebSocketClient
from datetime import datetime, UTC
from model.FavoritesOnlyStrategy import FavoritesOnlyStrategy
from pathlib import Path
import pandas as pd
import asyncio

def load_private_key(key_file: str):
    with open(key_file, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)

def load_http_client(key_id: str, key_file: str, env: KalshiEnvironment):
    return KalshiHttpClient(
        key_id=key_id,
        private_key=load_private_key(key_file),
        environment=env,
    )

def load_ws_client(key_id: str, key_file: str, env: KalshiEnvironment):
    return KalshiWebSocketClient(
        key_id=key_id,
        private_key=load_private_key(key_file),
        environment=env,
    )

def iso_to_ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def load_history(csv_file: Path) -> list[dict]:
    df = pd.read_csv(csv_file)

    required_cols = [
        "ts",
        "time",
        "open_yes_price_dollars",
        "high_yes_price_dollars",
        "low_yes_price_dollars",
        "close_yes_price_dollars",
        "volume_contracts",
        "num_trades",
    ]

    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"{csv_file.name}: missing columns: {missing}")

    df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
    df["open_yes_price_dollars"] = pd.to_numeric(df["open_yes_price_dollars"], errors="coerce")
    df["high_yes_price_dollars"] = pd.to_numeric(df["high_yes_price_dollars"], errors="coerce")
    df["low_yes_price_dollars"] = pd.to_numeric(df["low_yes_price_dollars"], errors="coerce")
    df["close_yes_price_dollars"] = pd.to_numeric(df["close_yes_price_dollars"], errors="coerce")
    df["volume_contracts"] = pd.to_numeric(df["volume_contracts"], errors="coerce")
    df["num_trades"] = pd.to_numeric(df["num_trades"], errors="coerce")

    df = df.dropna(subset=["ts"]).copy()
    df["ts"] = df["ts"].astype(int)
    df["num_trades"] = df["num_trades"].fillna(0).astype(int)

    history = []
    for _, row in df.iterrows():
        history.append({
            "ts": row["ts"],
            "time": row["time"],
            "open_yes_price_dollars": row["open_yes_price_dollars"],
            "high_yes_price_dollars": row["high_yes_price_dollars"],
            "low_yes_price_dollars": row["low_yes_price_dollars"],
            "close_yes_price_dollars": row["close_yes_price_dollars"],
            "volume_contracts": row["volume_contracts"],
            "num_trades": row["num_trades"],
        })

    return history

def load_market_state(state) -> MarketState:
    return MarketState(open_ts=state.get("ts"),
                       close_ts=state.get("ts"),
                       closing_ask=state.get("close_yes_price_dollars"),
                       live_ask=state.get("close_yes_price_dollars"),
                       last_price=state.get("close_yes_price_dollars"))


async def run_one_ticker(ticker_id, trader, strategy_config, strategy_state):
    strategy = SmaCrossoverStrategy(config=strategy_config, trader=trader)
    csv_file = Path(f"output_data/{ticker_id}_live_1s_ohlc.csv")
    history = load_history(csv_file)

    for tick in history:
        market_state = load_market_state(tick)
        await strategy.update(ticker_id, strategy_state, market_state)

def setup_trader(env: KalshiEnvironment) -> LiveTrader | None:
    load_dotenv()
    KEYID = os.getenv("PROD_KEYID")
    KEYFILE = os.getenv("PROD_KEYFILE")
    try:
        http_client = load_http_client(KEYID, KEYFILE, env)
        log.info("Loaded http_client.")
    except Exception as e:
        log.error(f"Could not load http_client: {e}")
        return
    
    try:
        bal_resp_dict = http_client.get_balance()
        log.info("Retrieved Kalshi User Balance.")
    except Exception as e:
        log.error(f"Could not get balance: {e}")
        return
    
    try:
        limits = http_client.get_account_limits()
        log.info("Retrieved Kalshi User Account Limits.")
        log.info(f"Limits: \n{limits}")
    except Exception as e:
        log.error(f"Could not get account limits: {e}")
        return

    kalshi_portfolio = Portfolio.from_dict(bal_resp_dict)
    return LiveTrader(portfolio=kalshi_portfolio, http_client=http_client)

def setup_ws_client(env: KalshiEnvironment) -> LiveTrader | None:
    load_dotenv()
    KEYID = os.getenv("PROD_KEYID")
    KEYFILE = os.getenv("PROD_KEYFILE")
    try:
        ws_client = load_ws_client(KEYID, KEYFILE, env)
        log.info("Loaded ws client.")
    except Exception as e:
        log.error(f"Could not load ws client: {e}")
        return
    return ws_client

def run_live():
    env = KalshiEnvironment.PROD
    run_type = RunType.SINGLE_EVENT
    trader = setup_trader(env)
    assert trader is not None
    log.info("Trader configured.")

    tickers_arr = ["KXNBAGAME-26APR14PORPHX-PHX"]
    market_states: dict[str, MarketState] = {}
    strategies: dict[str, FavoritesOnlyStrategy] = {}
    ticker_to_market_dict: dict[str, CurrentStrategyState] = {}
    for ticker in tickers_arr:
        ticker_to_market_dict[ticker] = CurrentStrategyState(
            entry_price=0, 
            contract_count=0, 
            entries_done=0, 
            in_position=False, 
            done=False)
        market_state = MarketState(
                open_ts=None,
                close_ts=None,
                closing_ask=None,
                live_ask=None,
                last_price=None,
            )
        market_states[ticker] = market_state
        strategies[ticker] = FavoritesOnlyStrategy(trader=trader, strategy_state=ticker_to_market_dict[ticker])
    
    ws_client = setup_ws_client(env)
    assert ws_client is not None

    async def ws_message_handler(data: dict):
        msg_type = data.get("type") or data.get("msg_type")
        if msg_type in {"subscribed", "error", "pong"}:
            return

        payload = data.get("msg") or data.get("data") or data

        rec_ticker = (
            payload.get("market_ticker")
            or payload.get("ticker")
            or payload.get("market")
        )

        yes_ask = payload.get("yes_ask_dollars")
        no_ask = payload.get("no_ask_dollars")
        last_price = payload.get("price_dollars")

        if yes_ask is None and no_ask is None and last_price is None:
            return

        market_states[rec_ticker] = MarketState(
            open_ts=market_states[rec_ticker].open_ts,
            close_ts=market_states[rec_ticker].close_ts,
            closing_ask=market_states[rec_ticker].closing_ask,
            live_ask=float(yes_ask) if yes_ask is not None else market_states[rec_ticker].live_ask,
            last_price=float(last_price) if last_price is not None else market_states[rec_ticker].last_price,
        )
        
    async def print_loop():
        while True:
            now = datetime.now(UTC).isoformat()
            for ticker, st in market_states.items():
                print({
                    "time": now,
                    "ticker": ticker,
                    "live_ask": st.live_ask,
                    "last_price": st.last_price,
                    "open_ts": st.open_ts,
                    "close_ts": st.close_ts,
                    "closing_ask": st.closing_ask,
                })
            await asyncio.sleep(3)
    async def asmain():
        ws_client._tickers = tickers_arr
        ws_client._message_handler = ws_message_handler

        await asyncio.gather(
            ws_client.connect(),
            print_loop(),
        )

    asyncio.run(asmain())

def base_simulation_run():
    initial_balance = 100000
    initial_portfolio = Portfolio(balance=initial_balance, portfolio_value=0, updated_ts=0)
    trader = SimulatedTrader(portfolio=initial_portfolio)
    tickers_arr = []
    with open("favorites_tickers.txt", "r") as f:
        tickers_arr = [line.strip() for line in f if line.strip()]
    ticker_to_market_dict = {}
    for ticker in tickers_arr:
        ticker_to_market_dict[ticker] = CurrentStrategyState(
            entry_price=0, 
            contract_count=0, 
            entries_done=0, 
            in_position=False, 
            done=False)

        strategy = FavoritesOnlyStrategy(trader=trader, strategy_state=ticker_to_market_dict[ticker])
        csv_file = Path(f"output_data/pregame_favorites/{ticker}_live_1s_ohlc.csv")
        history = load_history(csv_file)
        last_market_state = None
        for tick in history:
            market_state = load_market_state(tick)
            last_market_state = market_state
            strategy.update(ticker, market_state)

        #handle bad data case, just sell the shares at cost
        strat_state = ticker_to_market_dict[ticker]
        if strat_state.in_position:
            log.warning("\t still in position...")
            order = MarketOrder(
                    ticker="simulated",
                    favored_side="yes",
                    count=strat_state.contract_count,
                    limit_price_dollars=last_market_state.live_ask,
                )
            strategy.trader.place_exit(ticker, order)
            strategy.strategy_state.done = True


def main():
    config_file = "config.json"
    log.info(f"Executing main with configuration: {config_file}")
    # For now our config is just hardcoded here
    config = {"simulated": False}

    if(config.get("simulated")):
        log.info("Executing simulated algorithm.")
        base_simulation_run()

    else:
        # TODO get from config
        log.info("Executing live algorithm.")
        run_live()


if __name__=="__main__":
    main()


# async def run_simulated():
#     # $1000 or load from config...
#     initial_balance = 1000.0
#     initial_balance_cents = initial_balance * 100.0
#     is_simulated = True
    
#     initial_portfolio = KalshiPortfolioResponse(balance=initial_balance_cents, portfolio_value=0.0, updated_ts=0)

#     # For each market (i.e. KXNBAGAME...) we need a CurrentStrategyState associated with the ticker
#     # This means we need to know how many tickers we are tracking
#     # For this example we are using 2 games to test
#     tickers_arr = ["KXNBAGAME-26APR06CLEMEM-CLE", "KXNBAGAME-26APR09LALGSW-GSW"]
#     ticker_to_market_dict = {}
#     for ticker in tickers_arr:
#         ticker_to_market_dict[ticker] = CurrentStrategyState(
#             entry_price=0, 
#             contract_count=0, 
#             entries_done=0, 
#             in_position=False, 
#             done=False)

#     # This is our only Trader instance   
#     trader = Trader(portfolio=initial_portfolio, simulated=is_simulated, http_client=None)

#     strategy_config = StrategyConfig(simulated=is_simulated,
#                                      entry_ratio=0.2, 
#                                      stop_loss_ratio=0.2, 
#                                      exit_ratio=0.15,
#                                      secondary_exit_ratio=0.30,
#                                      max_entries=100,
#                                      min_entry_ask=0.25, # if it falls to 0.x * inital opening price, stop trading 
#                                      balance_fraction=0.05)
    

    
#     strategy = SmaCrossoverStrategy(config=strategy_config, trader=trader)
#     await asyncio.gather(*[
#         run_one_ticker(
#             ticker,
#             trader,
#             strategy_config,
#             ticker_to_market_dict[ticker],
#         )
#         for ticker in tickers_arr
#     ])