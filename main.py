
from loguru import logger as log
from traders.Trader import Trader
from utils.utils import KalshiPortfolioResponse, MarketState, KalshiEnvironment
import os
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization
from KalshiClients.KalshiClients import KalshiHttpClient, KalshiWebSocketClient
from datetime import datetime

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
        private_key=load_private_key(),
        environment=env,
    )

def iso_to_ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def run_simulated():
    # initial_market_state = MarketState(...)
    # initial_portfolio = KalshiPortfolioResponse(...)
    # trader = Trader(st=initial_market_state, portfolio=initial_portfolio, simulated=True, http_client=None)
    return

def run_live(env: KalshiEnvironment):
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
    except Exception as e:
        log.error(f"Could not get account limits: {e}")
        return

    try:
            #TODO hardcoding these for now...
            ticker = "KXNBAGAME-26APR09LALGSW-GSW"
            favored_side = "yes"
            user_closing_ask = 0.5
            market = http_client.get(f"{http_client.markets_url}/{ticker}")["market"]
            state = MarketState(
                ticker=ticker,
                favored_side=favored_side,
                open_ts=iso_to_ts(market["open_time"]),
                close_ts=iso_to_ts(market["close_time"]),
            )
            px = http_client.get_market_prices(ticker)
            state.closing_ask = user_closing_ask
            state.live_ask = state.closing_ask
            last_price = px.get("last_price")
            state.last_price = float(last_price) if last_price is not None else None
    except Exception as e:
        log.error(f"Could not get account limits: {e}")

    kalshi_portfolio = KalshiPortfolioResponse.from_dict(bal_resp_dict)
    trader = Trader(st=state, portfolio=kalshi_portfolio, simulated=False, http_client=None)

def main():
    config_file = "config.json"
    log.info(f"Executing main with configuration: {config_file}")
    # For now our config is just hardcoded here
    config = {"simulated": False, "data_file": "test_data.csv"}

    if(config.get("simulated")):
        log.info("Executing simulated algorithm.")
        run_simulated()
    else:
        # TODO get from config
        log.info("Executing live algorithm.")
        env = KalshiEnvironment.PROD
        run_live(env)


if __name__=="__main__":
    main()