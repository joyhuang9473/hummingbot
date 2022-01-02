from decimal import Decimal
import logging
import time
import pandas as pd
import numpy as np
from typing import (
    List,
    Dict
)

from hummingbot.core.clock import Clock
from hummingbot.core.event.events import OrderType, PriceType, TradeType
from hummingbot.core.data_type.limit_order import LimitOrder
from hummingbot.core.utils import map_df_to_str
from hummingbot.strategy.market_trading_pair_tuple import MarketTradingPairTuple
from hummingbot.strategy.asset_price_delegate import AssetPriceDelegate
from hummingbot.strategy.utils import order_age
from hummingbot.strategy.strategy_py_base import StrategyPyBase
from hummingbot.strategy.hanging_orders_tracker import HangingOrdersTracker
from .data_types import (
    Proposal,
    PriceSize
)
from hummingbot.logger import HummingbotLogger
from .grid_order_tracker import GridOrderTracker

hws_logger = None


class GridOrder(StrategyPyBase):
    OPTION_LOG_CREATE_ORDER = 1 << 3
    OPTION_LOG_MAKER_ORDER_FILLED = 1 << 4
    OPTION_LOG_STATUS_REPORT = 1 << 5
    OPTION_LOG_ALL = 0x7fffffffffffffff

    @classmethod
    def logger(cls) -> HummingbotLogger:
        global hws_logger
        if hws_logger is None:
            hws_logger = logging.getLogger(__name__)
        return hws_logger

    def __init__(self,
                 market_info: MarketTradingPairTuple,
                 price_ceiling: Decimal,
                 price_floor: Decimal,
                 base_percentage: Decimal,
                 quote_percentage: Decimal,
                 rebalance_percentage: Decimal,
                 cmap: Dict,
                 order_level_amount: Decimal = Decimal(0),
                 order_levels: int = 1,
                 order_refresh_time: float = 30.0,
                 max_order_age: float = 30.0,
                 filled_order_delay: float = 60.0,
                 status_report_interval: float = 900,
                 price_type: str = "mid_price",
                 asset_price_delegate: AssetPriceDelegate = None,
                 hanging_orders_cancel_pct: Decimal = Decimal("0.1"),
                 logging_options: int = OPTION_LOG_ALL,
                 should_wait_order_cancel_confirmation = True,
                 ):
        super().__init__()
        self._market_info = market_info
        self._connector_ready = False
        self._order_completed = False
        self.add_markets([market_info.market])

        self._cmap = cmap

        self._price_ceiling = float(price_ceiling)
        self._price_floor = float(price_floor)

        self._base_percentage = float(base_percentage)
        self._quote_percentage = float(quote_percentage)
        self._rebalance_percentage = float(rebalance_percentage)

        self._hanging_orders_tracker = HangingOrdersTracker(self, hanging_orders_cancel_pct)
        self._sb_order_tracker = GridOrderTracker()
        self._logging_options = logging_options

        self._price_type = self.get_price_type(price_type)
        self._asset_price_delegate = asset_price_delegate

        self._order_refresh_time = order_refresh_time
        self._max_order_age = max_order_age
        self._filled_order_delay = filled_order_delay
        self._last_timestamp = 0
        self._cancel_timestamp = 0
        self._create_timestamp = 0
        self._filled_buys_balance = 0
        self._filled_sells_balance = 0
        self._last_own_trade_price = Decimal('nan')
        self._status_report_interval = status_report_interval
        self._should_wait_order_cancel_confirmation = should_wait_order_cancel_confirmation

        self._buy_levels = 1
        self._sell_levels = 1
        self._order_level_amount = order_level_amount
        self._order_amount = 0
        self._order_levels = order_levels

    @property
    def filled_order_delay(self) -> float:
        return self._filled_order_delay

    @property
    def price_ceiling(self) -> float:
        return self._price_ceiling

    @property
    def price_floor(self) -> float:
        return self._price_floor

    @property
    def base_asset(self):
        return self._market_info.base_asset

    @property
    def quote_asset(self):
        return self._market_info.quote_asset

    @property
    def trading_pair(self):
        return self._market_info.trading_pair

    @property
    def market_info_to_active_orders(self) -> Dict[MarketTradingPairTuple, List[LimitOrder]]:
        return self._sb_order_tracker.market_pair_to_active_orders

    @property
    def active_orders(self) -> List[LimitOrder]:
        if self._market_info not in self.market_info_to_active_orders:
            return []
        return self.market_info_to_active_orders[self._market_info]

    @property
    def hanging_orders_cancel_pct(self) -> Decimal:
        return self._hanging_orders_tracker._hanging_orders_cancel_pct

    @hanging_orders_cancel_pct.setter
    def hanging_orders_cancel_pct(self, value: Decimal):
        self._hanging_orders_tracker._hanging_orders_cancel_pct = value

    @property
    def hanging_order_ids(self) -> List[str]:
        return [o.order_id for o in self._hanging_orders_tracker.strategy_current_hanging_orders]

    @property
    def active_non_hanging_orders(self) -> List[LimitOrder]:
        orders = [o for o in self.active_orders if not self._hanging_orders_tracker.is_order_id_in_hanging_orders(o.client_order_id)]
        return orders

    @property
    def hanging_orders_tracker(self):
        return self._hanging_orders_tracker

    @property
    def max_order_age(self) -> float:
        return self._max_order_age

    def get_price(self) -> float:
        price_provider = self._asset_price_delegate or self._market_info
        if self._price_type is PriceType.LastOwnTrade:
            price = self._last_own_trade_price
        elif self._price_type is PriceType.InventoryCost:
            price = price_provider.market.get_price_by_type(self.trading_pair, PriceType.MidPrice)
        else:
            price = price_provider.market.get_price_by_type(self.trading_pair, self._price_type)

        if price.is_nan():
            price = price_provider.market.get_price_by_type(self.trading_pair, PriceType.MidPrice)

        return price

    def start(self, clock: Clock, timestamp: float):
        # StrategyPyBase.c_start(self, clock, timestamp)
        self._last_timestamp = timestamp
        self._hanging_orders_tracker.register_events(self.active_markets)

    def stop(self, clock: Clock):
        self._hanging_orders_tracker.unregister_events(self.active_markets)
        # StrategyPyBase.c_stop(self, clock)

    # After initializing the required variables, we define the tick method.
    # The tick method is the entry point for the strategy.
    def tick(self, timestamp: float):
        # StrategyPyBase.c_tick(self, timestamp)

        try:
            if not self._connector_ready:
                self._connector_ready = self._market_info.market.ready
            if not self._connector_ready:
                self.logger().warning(f"{self._market_info.market.name} is not ready. Please wait...")
                return
            # else:
            #     self.logger().warning(f"{self._market_info.market.name} is ready. Trading started")

            proposal = None
            if self._create_timestamp <= self.current_timestamp:
                base_quantity = float(self._market_info.market.get_available_balance(self.base_asset))
                base_balance = base_quantity * float(self.get_price())
                quote_balance = float(self._market_info.market.get_available_balance(self.quote_asset))

                # 1. Create base order proposals
                proposal = self.create_base_proposal(base_balance, quote_balance)
                # 2. Apply functions that limit numbers of buys and sells proposal
                self.apply_order_levels_modifiers(proposal)
                # 3. Apply functions that modify orders price
                # self.apply_order_price_modifiers(proposal)
                # 4. Apply functions that modify orders size
                # self.apply_order_size_modifiers(proposal)
                # 5. Apply budget constraint, i.e. can't buy/sell more than what you have.
                # self.apply_budget_constraint(proposal)

            self._hanging_orders_tracker.process_tick()

            self.cancel_active_orders_on_max_age_limit()
            # self.cancel_active_orders(proposal)
            # self.cancel_orders_below_min_spread()
            if self.to_create_orders(proposal):
                self.execute_orders_proposal(proposal)
        finally:
            self._last_timestamp = timestamp

    def create_base_proposal(self, base_balance, quote_balance):
        market = self._market_info.market
        buys = []
        sells = []

        buy_reference_price = market.get_price_by_type(self.trading_pair, PriceType.BestBid)
        sell_reference_price = market.get_price_by_type(self.trading_pair, PriceType.BestAsk)

        total_usd = base_balance + quote_balance
        base_percentage = float(100 * base_balance / total_usd)

        # First to check if a customized order override is configured, otherwise the proposal will be created according
        # to order spread, amount, and levels setting.
        if not buy_reference_price.is_nan() and (base_percentage < (self._base_percentage - self._rebalance_percentage)):
            for level in range(0, self._buy_levels):
                price = buy_reference_price
                buy_reference_price = float(buy_reference_price)
                size = float("{:.2f}".format(quote_balance * self._rebalance_percentage / 100.0 / buy_reference_price))
                if size > 0:
                    buys.append(PriceSize(Decimal(price), Decimal(size)))
                    self._order_amount = size
        elif not sell_reference_price.is_nan() and (base_percentage > (self._base_percentage + self._rebalance_percentage)):
            for level in range(0, self._sell_levels):
                price = sell_reference_price
                size = float("{:.2f}".format(base_balance * self._rebalance_percentage / 100.0))
                if size > 0:
                    sells.append(PriceSize(Decimal(price), Decimal(size)))
                    self._order_amount = size

        return Proposal(buys, sells)

    def apply_order_levels_modifiers(self, proposal: Proposal):
        self.apply_price_band(proposal)

    def apply_price_band(self, proposal: Proposal):
        if self.price_ceiling > 0 and self.get_price() >= self.price_ceiling:
            proposal.buys = []
            proposal.sells = []
        if self.price_floor > 0 and self.get_price() <= self.price_floor:
            proposal.buys = []
            proposal.sells = []

    # TODO
    # def apply_order_price_modifiers(self, proposal: Proposal):
    #     """
    #     Compare the market price with the top bid and top ask price
    #     """
    #     return

    # TODO
    # def apply_order_size_modifiers(self, proposal: Proposal):
    #     return

    # TODO
    # def apply_budget_constraint(self, proposal: Proposal):
    #     return

    def to_create_orders(self, proposal: Proposal):
        non_hanging_orders_non_cancelled = [o for o in self.active_non_hanging_orders if not
                                            self._hanging_orders_tracker.is_potential_hanging_order(o)]
        return (self._create_timestamp < self.current_timestamp
                and (not self._should_wait_order_cancel_confirmation or
                     len(self._sb_order_tracker.in_flight_cancels) == 0)
                and proposal is not None
                and len(non_hanging_orders_non_cancelled) == 0)

    def execute_orders_proposal(self, proposal: Proposal):
        expiration_seconds = self._order_refresh_time
        # bid_order_id = None
        # ask_order_id = None
        orders_created = False

        if len(proposal.buys) > 0:
            if self._logging_options & self.OPTION_LOG_CREATE_ORDER:
                price_quote_str = [f"{buy.size} {self.base_asset}, "
                                   f"{buy.price} {self.quote_asset}"
                                   for buy in proposal.buys]
                self.logger().info(
                    f"({self.trading_pair}) Creating {len(proposal.buys)} bid orders "
                    f"at (Size, Price): {price_quote_str}"
                )

            for idx, buy in enumerate(proposal.buys):
                # bid_order_id = self.buy_with_specific_market(
                _ = self.buy_with_specific_market(
                    self._market_info,
                    buy.size,
                    order_type=OrderType.LIMIT,
                    price=buy.price,
                    expiration_seconds=expiration_seconds
                )
                orders_created = True

        if len(proposal.sells) > 0:
            if self._logging_options & self.OPTION_LOG_CREATE_ORDER:
                price_quote_str = [f"{sell.size} {self.base_asset}, "
                                   f"{sell.price} {self.quote_asset}"
                                   for sell in proposal.sells]
                self.logger().info(
                    f"({self.trading_pair}) Creating {len(proposal.sells)} ask "
                    f"orders at (Size, Price): {price_quote_str}"
                )

            for idx, sell in enumerate(proposal.sells):
                # ask_order_id = self.sell_with_specific_market(
                _ = self.sell_with_specific_market(
                    self._market_info,
                    sell.size,
                    order_type=OrderType.LIMIT,
                    price=sell.price,
                    expiration_seconds=expiration_seconds
                )
                orders_created = True

        if orders_created:
            self.set_timers()

    def set_timers(self):
        next_cycle = self.current_timestamp + self._order_refresh_time
        if self._create_timestamp <= self.current_timestamp:
            self._create_timestamp = next_cycle
        if self._cancel_timestamp <= self.current_timestamp:
            self._cancel_timestamp = min(self._create_timestamp, next_cycle)

    def format_status(self) -> str:
        if not self._connector_ready:
            return "Market connectors are not ready."

        lines = []
        warning_lines = []

        warning_lines.extend(self.network_warning([self._market_info]))

        markets_df = map_df_to_str(self.market_status_data_frame([self._market_info]))
        lines.extend(["", "  Markets:"] + ["    " + line for line in markets_df.to_string(index=False).split("\n")])

        assets_df = map_df_to_str(self.pure_mm_assets_df(True))

        first_col_length = max(*assets_df[0].apply(len))
        df_lines = assets_df.to_string(index=False, header=False,
                                       formatters={0: ("{:<" + str(first_col_length) + "}").format}).split("\n")
        lines.extend(["", "  Assets:"] + ["    " + line for line in df_lines])

        # See if there're any open orders.
        if len(self.active_orders) > 0:
            df = map_df_to_str(self.active_orders_df())
            lines.extend(["", "  Orders:"] + ["    " + line for line in df.to_string(index=False).split("\n")])
        else:
            lines.extend(["", "  No active maker orders."])

        warning_lines.extend(self.balance_warning([self._market_info]))

        if len(warning_lines) > 0:
            lines.extend(["", "*** WARNINGS ***"] + warning_lines)

        return "\n".join(lines)

    def market_status_data_frame(self, market_trading_pair_tuples: List[MarketTradingPairTuple]) -> pd.DataFrame:
        markets_data = []
        markets_columns = ["Exchange", "Market", "Best Bid", "Best Ask", "Ref Price (MidPrice)"]

        market_books = [(self._market_info.market, self._market_info.trading_pair)]

        for market, trading_pair in market_books:
            bid_price = market.get_price_by_type(self.trading_pair, PriceType.BestBid)
            ask_price = market.get_price_by_type(self.trading_pair, PriceType.BestAsk)
            ref_price = market.get_price_by_type(self.trading_pair, PriceType.MidPrice)

            markets_data.append([
                market.display_name,
                trading_pair,
                float(bid_price),
                float(ask_price),
                float(ref_price)
            ])
        return pd.DataFrame(data=markets_data, columns=markets_columns).replace(np.nan, '', regex=True)

    def pure_mm_assets_df(self, to_show_current_pct: bool) -> pd.DataFrame:
        market, trading_pair, base_asset, quote_asset = self._market_info
        price = self._market_info.get_mid_price()
        base_balance = float(market.get_balance(base_asset))
        quote_balance = float(market.get_balance(quote_asset))
        available_base_balance = float(market.get_available_balance(base_asset))
        available_quote_balance = float(market.get_available_balance(quote_asset))
        base_value = base_balance * float(price)
        total_in_quote = base_value + quote_balance
        base_ratio = base_value / total_in_quote if total_in_quote > 0 else 0
        quote_ratio = quote_balance / total_in_quote if total_in_quote > 0 else 0
        data = [
            ["", base_asset, quote_asset],
            ["Total Balance", round(base_balance, 4), round(quote_balance, 4)],
            ["Available Balance", round(available_base_balance, 4), round(available_quote_balance, 4)],
            [f"Current Value ({quote_asset})", round(base_value, 4), round(quote_balance, 4)]
        ]
        if to_show_current_pct:
            data.append(["Current %", f"{base_ratio:.1%}", f"{quote_ratio:.1%}"])
        df = pd.DataFrame(data=data)
        return df

    def active_orders_df(self) -> pd.DataFrame:
        market, trading_pair, base_asset, quote_asset = self._market_info
        price = market.get_price_by_type(self.trading_pair, PriceType.MidPrice)
        active_orders = self.active_orders

        no_sells = len([o for o in active_orders if not o.is_buy and o.client_order_id and
                        not self._hanging_orders_tracker.is_order_id_in_hanging_orders(o.client_order_id)])

        active_orders.sort(key=lambda x: x.price, reverse=True)
        columns = ["Level", "Type", "Price", "Spread", "Amount (Orig)", "Amount (Adj)", "Age"]
        data = []
        lvl_buy, lvl_sell = 0, 0
        for idx in range(0, len(active_orders)):
            order = active_orders[idx]
            is_hanging_order = self._hanging_orders_tracker.is_order_id_in_hanging_orders(order.client_order_id)
            if not is_hanging_order:
                if order.is_buy:
                    level = lvl_buy + 1
                    lvl_buy += 1
                else:
                    level = no_sells - lvl_sell
                    lvl_sell += 1
            spread = 0 if price == 0 else abs(order.price - price) / price
            age = "n/a"
            # // indicates order is a paper order so 'n/a'. For real orders, calculate age.
            if "//" not in order.client_order_id:
                age = pd.Timestamp(int(time.time()) - int(order.client_order_id[-16:]) / 1e6,
                                   unit='s').strftime('%H:%M:%S')

            if is_hanging_order:
                level_for_calculation = lvl_buy if order.is_buy else lvl_sell
                amount_orig = self._order_amount + ((level_for_calculation - 1) * self._order_level_amount)
                level = "hang"
            else:
                amount_orig = ""

            data.append([
                level,
                "buy" if order.is_buy else "sell",
                float(order.price),
                f"{spread:.2%}",
                amount_orig,
                float(order.quantity),
                age
            ])

        return pd.DataFrame(data=data, columns=columns)

    # Emit a log message when the order completes
    def did_complete_buy_order(self, order_completed_event):
        order_id = order_completed_event.order_id
        limit_order_record = self._sb_order_tracker.get_limit_order(self._market_info, order_id)
        if limit_order_record is None:
            return
        # active_sell_ids = [x.client_order_id for x in self.active_orders if not x.is_buy]
        _ = [x.client_order_id for x in self.active_orders if not x.is_buy]

        # delay order creation by filled_order_dalay (in seconds)
        self._create_timestamp = self.current_timestamp + self._filled_order_delay
        self._cancel_timestamp = min(self._cancel_timestamp, self._create_timestamp)

        self._filled_buys_balance += 1
        self._last_own_trade_price = limit_order_record.price

        self.log_with_clock(
            logging.INFO,
            f"({self.trading_pair}) Maker buy order {order_id} "
            f"({limit_order_record.quantity} {limit_order_record.base_currency} @ "
            f"{limit_order_record.price} {limit_order_record.quote_currency}) has been completely filled."
        )
        self.notify_hb_app_with_timestamp(
            f"Maker BUY order {limit_order_record.quantity} {limit_order_record.base_currency} @ "
            f"{limit_order_record.price} {limit_order_record.quote_currency} is filled."
        )

    def did_complete_sell_order(self, order_completed_event):
        order_id = order_completed_event.order_id
        limit_order_record = self._sb_order_tracker.get_limit_order(self._market_info, order_id)
        if limit_order_record is None:
            return
        # active_buy_ids = [x.client_order_id for x in self.active_orders if x.is_buy]
        _ = [x.client_order_id for x in self.active_orders if x.is_buy]

        # delay order creation by filled_order_dalay (in seconds)
        self._create_timestamp = self.current_timestamp + self._filled_order_delay
        self._cancel_timestamp = min(self._cancel_timestamp, self._create_timestamp)

        self._filled_sells_balance += 1
        self._last_own_trade_price = limit_order_record.price

        self.log_with_clock(
            logging.INFO,
            f"({self.trading_pair}) Maker sell order {order_id} "
            f"({limit_order_record.quantity} {limit_order_record.base_currency} @ "
            f"{limit_order_record.price} {limit_order_record.quote_currency}) has been completely filled."
        )
        self.notify_hb_app_with_timestamp(
            f"Maker SELL order {limit_order_record.quantity} {limit_order_record.base_currency} @ "
            f"{limit_order_record.price} {limit_order_record.quote_currency} is filled."
        )

    def did_fill_order(self, order_filled_event):
        order_id = order_filled_event.order_id
        market_info = self._sb_order_tracker.c_get_shadow_market_pair_from_order_id(order_id)

        if market_info is not None:
            limit_order_record = self._sb_order_tracker.c_get_shadow_limit_order(order_id)
            # order_fill_record = (limit_order_record, order_filled_event)
            _ = (limit_order_record, order_filled_event)

            if order_filled_event.trade_type is TradeType.BUY:
                if self._logging_options & self.OPTION_LOG_MAKER_ORDER_FILLED:
                    self.log_with_clock(
                        logging.INFO,
                        f"({market_info.trading_pair}) Maker buy order of "
                        f"{order_filled_event.amount} {market_info.base_asset} filled."
                    )
            else:
                if self._logging_options & self.OPTION_LOG_MAKER_ORDER_FILLED:
                    self.log_with_clock(
                        logging.INFO,
                        f"({market_info.trading_pair}) Maker sell order of "
                        f"{order_filled_event.amount} {market_info.base_asset} filled."
                    )

    def cancel_active_orders_on_max_age_limit(self):
        """
        Cancels active non hanging orders if they are older than max age limit
        """
        active_orders = self.active_non_hanging_orders

        if active_orders and any(order_age(o) > self._max_order_age for o in active_orders):
            for order in active_orders:
                self.cancel_order(self._market_info, order.client_order_id)

    # TODO
    # def cancel_active_orders(self, proposal: Proposal):
    #     """
    #     Cancels active non hanging orders, checks if the order prices are within tolerance threshold
    #     """
    #     return

    # TODO
    # def cancel_orders_below_min_spread(self):
    #     """
    #     Cancel Non-Hanging, Active Orders if Spreads are below minimum_spread
    #     """
    #     return

    def notify_hb_app(self, msg: str):
        if self._hb_app_notification:
            super().notify_hb_app(msg)

    def get_price_type(self, price_type_str: str) -> PriceType:
        if price_type_str == "mid_price":
            return PriceType.MidPrice
        elif price_type_str == "best_bid":
            return PriceType.BestBid
        elif price_type_str == "best_ask":
            return PriceType.BestAsk
        elif price_type_str == "last_price":
            return PriceType.LastTrade
        elif price_type_str == 'last_own_trade_price':
            return PriceType.LastOwnTrade
        elif price_type_str == 'inventory_cost':
            return PriceType.InventoryCost
        elif price_type_str == "custom":
            return PriceType.Custom
        else:
            raise ValueError(f"Unrecognized price type string {price_type_str}.")
