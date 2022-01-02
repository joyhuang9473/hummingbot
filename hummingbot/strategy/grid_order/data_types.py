from decimal import Decimal
from typing import List


class PriceSize:
    def __init__(self, price: Decimal, size: Decimal):
        self.price: Decimal = price
        self.size: Decimal = size

    def __repr__(self):
        return f"[ p: {self.price} s: {self.size} ]"


class Proposal:
    def __init__(self, buys: List[PriceSize], sells: List[PriceSize]):
        self.buys: List[PriceSize] = buys
        self.sells: List[PriceSize] = sells

    def __repr__(self):
        return f"{len(self.buys)} buys: {', '.join([str(o) for o in self.buys])} " \
               f"{len(self.sells)} sells: {', '.join([str(o) for o in self.sells])}"
