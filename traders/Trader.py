from loguru import logger as log
import uuid
from utils.utils import MarketState, KalshiPortfolioResponse
from KalshiClients.KalshiClients import KalshiHttpClient

class Trader:
    def __init__(self, st: MarketState, 
                 portfolio: KalshiPortfolioResponse, 
                 simulated: bool,
                 http_client: KalshiHttpClient) -> None:
        self.st = st
        self.portfolio = portfolio
        self.simulated = simulated
        self.http_client = http_client
        log.info("Trader constructed with fields:")
        log.info(f"Portfolio: {self.portfolio}")
        log.info(f"Market State: {self.st}")
        log.info(f"Simulated Flag: {self.simulated}")

    def get_market_state(self) -> MarketState:
        return self.st
    
    def get_portfolio(self) -> KalshiPortfolioResponse:
        return self.portfolio
    
    # def _available_balance_dollars(self) -> float:
    #     bal = self.http.get_balance()
    #     for key in ["balance", "cash_balance", "available_balance"]:
    #         if key in bal and bal[key] is not None:
    #             return float(bal[key]) / 100.0
    #     raise RuntimeError(f"Could not find balance field in: {bal}")

    # def _contracts_for_price(self, ask_price: float) -> int:
    #     balance = self._available_balance_dollars()
    #     budget = balance * self.balance_fraction
    #     contracts = max(1, math.floor(budget / ask_price))
    #     print("SIZE_CHECK", {
    #         "balance": balance,
    #         "balance_fraction": self.balance_fraction,
    #         "budget_dollars": budget,
    #         "ask_price_dollars": ask_price,
    #         "raw_contracts": budget / ask_price,
    #         "contracts_floor": math.floor(budget / ask_price),
    #         "contracts_final": contracts,
    #     })
    #     return contracts

    def place_entry(self, st: MarketState):
        count = self._contracts_for_price(st.live_ask)
        client_order_id = str(uuid.uuid4())
        print("ENTRY_ORDER", {
            "ticker": st.ticker,
            "side": st.favored_side,
            "live_ask": st.live_ask,
            "count": count,
            "notional_dollars": count * st.live_ask,
        })
        resp = self.http_client.buy_contract(
            ticker=st.ticker,
            side=st.favored_side,
            count=count,
            limit_price_dollars=st.live_ask,
            client_order_id=client_order_id,
        )
        st.in_position = True
        st.entry_price = st.live_ask
        st.contract_count = count
        st.entries_done += 1
        print("ENTRY", st.ticker, st.favored_side, st.live_ask, count, resp)

    def place_exit(self, st: MarketState, reason: str):
        client_order_id = str(uuid.uuid4())
        resp = self.http_client.sell_contract(
            ticker=st.ticker,
            side=st.favored_side,
            count=st.contract_count,
            limit_price_dollars=0.01,
            client_order_id=client_order_id,
        )
        print("EXIT", st.ticker, st.favored_side, st.live_ask, st.contract_count, reason, resp)
        st.in_position = False
        st.entry_price = None
        st.contract_count = 0
        if st.entries_done >= self.max_entries:
            st.done = True