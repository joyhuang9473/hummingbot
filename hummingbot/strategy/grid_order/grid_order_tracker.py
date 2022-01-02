from hummingbot.strategy.order_tracker import OrderTracker


class GridOrderTracker(OrderTracker):

    def __init__(self):
        super().__init__()

    # @property
    # def active_limit_orders(self) -> List[Tuple[ConnectorBase, LimitOrder]]:
    #     limit_orders = []
    #     for market_pair, orders_map in self._tracked_limit_orders.items():
    #         for limit_order in orders_map.values():
    #             limit_orders.append((market_pair.market, limit_order))
    #     return limit_orders

    # @property
    # def shadow_limit_orders(self) -> List[Tuple[ConnectorBase, LimitOrder]]:
    #     limit_orders = []
    #     for market_pair, orders_map in self._shadow_tracked_limit_orders.items():
    #         for limit_order in orders_map.values():
    #             limit_orders.append((market_pair.market, limit_order))
    #     return limit_orders

    # @property
    # def market_pair_to_active_orders(self) -> Dict[MarketTradingPairTuple, List[LimitOrder]]:
    #     market_pair_to_orders = {}
    #     market_pairs = self._tracked_limit_orders.keys()
    #     for market_pair in market_pairs:
    #         maker_orders = []
    #         for limit_order in self._tracked_limit_orders[market_pair].values():
    #             maker_orders.append(limit_order)
    #         market_pair_to_orders[market_pair] = maker_orders
    #     return market_pair_to_orders
