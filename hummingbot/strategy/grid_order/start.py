from hummingbot.strategy.market_trading_pair_tuple import MarketTradingPairTuple
from hummingbot.strategy.grid_order import GridOrder
from hummingbot.strategy.grid_order.grid_order_config_map import grid_order_config_map as c_map


def start(self):
    connector = c_map.get("connector").value.lower()
    market = c_map.get("market").value

    self._initialize_markets([(connector, [market])])
    base, quote = market.split("-")
    market_info = MarketTradingPairTuple(self.markets[connector], market, base, quote)
    self.market_trading_pair_tuples = [market_info]

    self.strategy = GridOrder(market_info,
                              c_map.get("price_ceiling").value,
                              c_map.get("price_floor").value,
                              c_map.get("base_percentage").value,
                              c_map.get("quote_percentage").value,
                              c_map.get("rebalance_percentage").value,
                              c_map)
