from loguru import logger as log
import uuid
from utils.utils import MarketOrder, CurrentStrategyState, KalshiPortfolioResponse
from KalshiClients.KalshiClients import KalshiHttpClient
import math
import asyncio

class Trader:
    def __init__(self,
                 portfolio: KalshiPortfolioResponse,
                 simulated: bool,
                 http_client: KalshiHttpClient | None = None):
        self.portfolio = portfolio
        self.simulated = simulated
        self.http_client = http_client
        self._lock = asyncio.Lock()
        log.info("Trader constructed with fields:")
        log.info(f"Portfolio: {self.portfolio}")
        log.info(f"Simulated Flag: {self.simulated}")

    def get_portfolio(self) -> KalshiPortfolioResponse:
        return self.portfolio

    def _available_balance_dollars(self) -> float:
        if self.simulated:
            return (self.portfolio.balance / 100.0)
        bal = self.http_client.get_balance()
        for key in ["balance", "cash_balance", "available_balance"]:
            if key in bal and bal[key] is not None:
                return float(bal[key]) / 100.0
        raise RuntimeError(f"Could not find balance field in: {bal}")

    async def place_entry(self, ticker_id: str, order: MarketOrder, state: CurrentStrategyState) -> None:
        async with self._lock:
            if state.in_position or state.done:
                return
            
            balance = self._available_balance_dollars()
            cost = order.count * order.limit_price_dollars
            if cost > balance:
                log.info(f"Balance of {balance} is not sufficient to place trade for {order.count} shares at {order.limit_price_dollars}")
                return
            client_order_id = str(uuid.uuid4())
            resp = None
            if self.simulated:
                self.portfolio.balance -= cost * 100.0 # times 100 because portfolio.balance is in cents
            else:
                # TODO handle exceptions here
                resp = self.http_client.buy_contract(
                    ticker=order.ticker,
                    side=order.favored_side,
                    count=order.count,
                    limit_price_dollars=order.limit_price_dollars,
                    client_order_id=client_order_id,
                )
            state.in_position = True
            state.entry_price = order.limit_price_dollars
            state.contract_count = order.count
            state.entries_done += 1
            log.info(
                "[ {} ] : ENTRY {} {} {} {} {}",
                ticker_id,
                order.ticker,
                order.favored_side,
                order.limit_price_dollars,
                state.contract_count,
                resp,
            )

    async def place_exit(self, ticker_id: str, order: MarketOrder, state: CurrentStrategyState, reason: str) -> None:
        async with self._lock:
            if not state.in_position:
                return

            proceeds = order.count * order.limit_price_dollars
            client_order_id = str(uuid.uuid4())
            resp = None
            if self.simulated:
                self.portfolio.balance += proceeds * 100.0
            else:
                # TODO handle exceptions here
                resp = self.http_client.sell_contract(
                    ticker=order.ticker,
                    side=order.favored_side,
                    count=order.count,
                    limit_price_dollars=order.limit_price_dollars,
                    client_order_id=client_order_id,
                )
            log.info(
                "[ {} ] :  EXIT {} {} {} {} {} {}",
                ticker_id,
                order.ticker,
                order.favored_side,
                order.limit_price_dollars,
                state.contract_count,
                reason,
                resp,
            )
            log.info(f"\t [ {ticker_id} ] Current Balance (After Exit): {self.portfolio.balance / 100.0}")
            state.in_position = False
            state.entry_price = None
            state.contract_count = 0
            # TODO WARN Note that we are never done!
            state.done = False

    # def place_entry(self, order: MarketOrder):
    #     client_order_id = str(uuid.uuid4())
    #     print("ENTRY_ORDER", {
    #         "ticker": order.ticker,
    #         "side": order.favored_side,
    #         "limit_price_dollars": order.limit_price_dollars,
    #         "count": order.count,
    #         "notional_dollars": order.count * order.limit_price_dollars,
    #     })
    #     resp = None
    #     if self.simulated:
    #         dollar_value = order.count * order.limit_price_dollars
    #         self.portfolio.balance -= dollar_value * 100.0
    #         # self.portfolio.portfolio_value += dollar_value
    #     else:
    #         # TODO handle exceptions here
    #         resp = self.http_client.buy_contract(
    #             ticker=order.ticker,
    #             side=order.favored_side,
    #             count=order.count,
    #             limit_price_dollars=order.limit_price_dollars,
    #             client_order_id=client_order_id,
    #         )
    #     self.trader_state.in_position = True
    #     self.trader_state.entry_price = order.limit_price_dollars
    #     self.trader_state.contract_count = order.count
    #     self.trader_state.entries_done += 1
    #     # log.info(f"\tCurrent Balance (After Entry): {self.portfolio.balance / 100.0}")
    #     print("ENTRY", order.ticker, order.favored_side, order.limit_price_dollars, self.trader_state.contract_count, resp)

    # def place_exit(self, order: MarketOrder, reason: str):
    #     client_order_id = str(uuid.uuid4())
    #     resp = None
    #     if self.simulated:
    #         dollar_value = order.count * order.limit_price_dollars
    #         self.portfolio.balance += dollar_value * 100.0
    #         # self.portfolio.portfolio_value -= dollar_value
    #     else:
    #         # TODO handle exceptions here
    #         resp = self.http_client.sell_contract(
    #             ticker=order.ticker,
    #             side=order.favored_side,
    #             count=order.count,
    #             limit_price_dollars=order.limit_price_dollars,
    #             client_order_id=client_order_id,
    #         )
    #     log.info(f"\tCurrent Balance (After Exit): {self.portfolio.balance / 100.0}")
    #     print("EXIT", order.ticker, order.favored_side, order.limit_price_dollars, self.trader_state.contract_count, reason, resp)
    #     self.trader_state.in_position = False
    #     self.trader_state.entry_price = None
    #     self.trader_state.contract_count = 0
    #     # TODO WARN Note that we are never done!
    #     self.trader_state.done = False