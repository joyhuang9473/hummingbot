from hummingbot.client.config.config_var import ConfigVar


def market_prompt() -> str:
    connector = limit_order_config_map.get("connector").value
    return f'Enter the token trading pair on {connector} >>> '


# List of parameters defined by the strategy
limit_order_config_map = {
    "startegy":
        ConfigVar(key="strategy",
                  prompt="",
                  default="limit_order",
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
}
