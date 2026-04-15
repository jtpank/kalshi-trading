from loguru import logger as log
import uuid
from utils.utils import MarketOrder, CurrentStrategyState, Portfolio
from KalshiClients.KalshiClients import KalshiHttpClient
from traders.BaseTrader import BaseTrader, EntryEnum, ExitEnum
import math

class LiveTrader(BaseTrader):
    def __init__(self,
                 portfolio: Portfolio,
                 http_client: KalshiHttpClient | None = None):
        self.portfolio = portfolio
        self.http_client = http_client
        log.info("Trader constructed with fields:")
        log.info(f"Portfolio: {self.portfolio}")

    def _available_balance_dollars(self) -> float:
        bal = self.http_client.get_balance()
        for key in ["balance", "cash_balance", "available_balance"]:
            if key in bal and bal[key] is not None:
                return float(bal[key]) / 100.0
        raise RuntimeError(f"Could not find balance field in: {bal}")

    def place_entry(self, ticker_id: str, order: MarketOrder) -> EntryEnum:
        balance = self._available_balance_dollars()
        cost = order.count * order.limit_price_dollars
        if cost > balance:
            log.info(f"Balance of {balance} is not sufficient to place trade for {order.count} shares at {order.limit_price_dollars}")
            return EntryEnum.FailureInsufficientBalance
        client_order_id = str(uuid.uuid4())
        # TODO handle exceptions here
        resp = self.http_client.buy_contract(
            ticker=order.ticker,
            side=order.favored_side,
            count=order.count,
            limit_price_dollars=order.limit_price_dollars,
            client_order_id=client_order_id,
        )
        # log.info(
        #     "[ {} ] : ENTRY {} {} {} {} {}",
        #     ticker_id,
        #     order.ticker,
        #     order.favored_side,
        #     order.limit_price_dollars,
        #     state.contract_count,
        #     resp,
        # )
        return EntryEnum.Success

    def place_exit(self, ticker_id: str, order: MarketOrder) -> ExitEnum:
        client_order_id = str(uuid.uuid4())
        # TODO handle exceptions here
        resp = self.http_client.sell_contract(
            ticker=order.ticker,
            side=order.favored_side,
            count=order.count,
            limit_price_dollars=order.limit_price_dollars,
            client_order_id=client_order_id,
        )
        # log.info(
        #     "[ {} ] :  EXIT {} {} {} {} {} {}",
        #     ticker_id,
        #     order.ticker,
        #     order.favored_side,
        #     order.limit_price_dollars,
        #     state.contract_count,
        #     reason,
        #     resp,
        # )
        # log.info(f"\t [ {ticker_id} ] Current Balance (After Exit): {self.portfolio.balance / 100.0}")
        return ExitEnum.Success