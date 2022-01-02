from hummingbot.client.config.config_var import ConfigVar
from hummingbot.client.config.config_validators import (
    validate_decimal
)


def market_prompt() -> str:
    connector = grid_order_config_map.get("connector").value
    return f'Enter the token trading pair on {connector} >>> '


# List of parameters defined by the strategy
grid_order_config_map = {
    "startegy":
        ConfigVar(key="strategy",
                  prompt="",
                  default="grid_order",
                  ),
    "connector":
        ConfigVar(key="connector",
                  prompt="Enter the name of the exchange >>> ",
                  prompt_on_new=True,
                  ),
    "market":
        ConfigVar(key="market",
                  prompt=market_prompt,
                  prompt_on_new=True,
                  ),
    "filled_order_delay":
        ConfigVar(key="filled_order_delay",
                  prompt="How long do you want to wait before placing the next order "
                         "if your order gets filled (in seconds)? >>> ",
                  type_str="float",
                  validator=lambda v: validate_decimal(v, min_value=0, inclusive=False),
                  default=60),
    "base_percentage":
        ConfigVar(key="base_percentage",
                  prompt="How many percentage do you want the base balance to fix on? >>> ",
                  type_str="float",
                  validator=lambda v: validate_decimal(v, min_value=0, inclusive=False),
                  default=50),
    "quote_percentage":
        ConfigVar(key="quote_percentage",
                  prompt="How many percentage do you want the quote balance to fix on? >>> ",
                  type_str="float",
                  validator=lambda v: validate_decimal(v, min_value=0, inclusive=False),
                  default=50),
    "rebalance_percentage":
        ConfigVar(key="rebalance_percentage",
                  prompt="How many percentage do you want the rebalance to fix on? >>> ",
                  type_str="float",
                  validator=lambda v: validate_decimal(v, min_value=0, inclusive=False),
                  default=1),
    "price_floor":
        ConfigVar(key="price_floor",
                  prompt="Enter the lowest price of the coin for the trading constraint >>> ",
                  prompt_on_new=True,
                  validator=lambda v: validate_decimal(v, min_value=0, inclusive=False),
                  ),
    "price_ceiling":
        ConfigVar(key="price_ceiling",
                  prompt="Enter the highest price of the coin for the trading constraint >>> ",
                  prompt_on_new=True,
                  validator=lambda v: validate_decimal(v, min_value=0, inclusive=False),
                  ),
}
