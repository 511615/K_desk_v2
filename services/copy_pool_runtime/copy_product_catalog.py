from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DemoProduct:
    symbol: str
    category: str
    contract_size: float
    volume_min: float = 0.01
    volume_step: float = 0.01


def _products(category: str, contract_size: float, *symbols: str) -> dict[str, DemoProduct]:
    return {
        symbol: DemoProduct(symbol, category, contract_size)
        for symbol in symbols
    }


DEMO_PRODUCTS: dict[str, DemoProduct] = {}
DEMO_PRODUCTS.update(_products(
    "forex",
    100_000.0,
    "USDCNH", "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD",
    "CADCHF", "CADJPY", "CHFJPY", "EURAUD", "EURCAD", "EURCHF",
    "EURGBP", "EURJPY", "EURNZD", "EURUSD", "GBPAUD", "GBPCAD",
    "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "NZDCAD", "NZDCHF",
    "NZDJPY", "NZDUSD", "USDCAD", "USDCHF", "USDJPY",
))
DEMO_PRODUCTS.update({
    "XAUUSD": DemoProduct("XAUUSD", "metal", 100.0),
    "XAGUSD": DemoProduct("XAGUSD", "metal", 5_000.0),
    "GAUCNH": DemoProduct("GAUCNH", "metal", 1_000.0),
    "XPDUSD": DemoProduct("XPDUSD", "metal", 10.0),
    "XPTUSD": DemoProduct("XPTUSD", "metal", 100.0),
    "NGASRoll": DemoProduct("NGASRoll", "energy", 10_000.0),
    "UKOILRoll": DemoProduct("UKOILRoll", "energy", 1_000.0),
    "USOILRoll": DemoProduct("USOILRoll", "energy", 1_000.0),
    "AUS200Roll": DemoProduct("AUS200Roll", "index", 10.0),
    "GER40Roll": DemoProduct("GER40Roll", "index", 10.0),
    "HKG50Roll": DemoProduct("HKG50Roll", "index", 20.0),
    "JPN225Roll": DemoProduct("JPN225Roll", "index", 200.0),
    "NAS100Roll": DemoProduct("NAS100Roll", "index", 20.0),
    "SPX500Roll": DemoProduct("SPX500Roll", "index", 50.0),
    "UK100Roll": DemoProduct("UK100Roll", "index", 10.0),
    "US30Roll": DemoProduct("US30Roll", "index", 10.0),
    "CN50Roll": DemoProduct("CN50Roll", "index", 10.0),
    "BTCUSD": DemoProduct("BTCUSD", "crypto", 1.0),
    "ETHUSD": DemoProduct("ETHUSD", "crypto", 10.0),
    "SOLUSD": DemoProduct("SOLUSD", "crypto", 100.0),
    "DOGEUSD": DemoProduct("DOGEUSD", "crypto", 10_000.0),
    "BCHUSD": DemoProduct("BCHUSD", "crypto", 100.0),
})
for _stock in ("Apple", "Alphabet", "Facebook", "NVIDIA", "Microsoft", "Amazon", "Tesla", "SpaceX"):
    DEMO_PRODUCTS[_stock] = DemoProduct(_stock, "stock", 1.0, volume_min=10.0, volume_step=1.0)


_ACCOUNT_SUFFIXES = {"ECN", "PRO", "CE", "E", "V", "S", "G", "GC", "GE"}
_ALIASES = {
    "UT100": "NAS100Roll",
    "NAS100": "NAS100Roll",
    "US30": "US30Roll",
    "US500": "SPX500Roll",
    "SPX500": "SPX500Roll",
    "DE40": "GER40Roll",
    "GER40": "GER40Roll",
    "HK50": "HKG50Roll",
    "HKG50": "HKG50Roll",
    "CHINA50": "CN50Roll",
    "CN50": "CN50Roll",
    "JP225": "JPN225Roll",
    "JPN225": "JPN225Roll",
    "UK100": "UK100Roll",
    "AUS200": "AUS200Roll",
    "USOIL": "USOILRoll",
    "UKOIL": "UKOILRoll",
    "NGAS": "NGASRoll",
}
_FUTURES_MONTH = re.compile(r"^[A-Z]{1,6}[FGHJKMNQUVXZ]\d{1,2}$")
_CASEFOLD_PRODUCTS = {key.upper(): key for key in DEMO_PRODUCTS}


def normalize_source_product(symbol: object) -> str | None:
    raw = str(symbol or "").strip()
    if not raw:
        return None
    pieces = raw.split(".")
    if len(pieces) > 1 and pieces[-1].upper() in _ACCOUNT_SUFFIXES:
        raw = ".".join(pieces[:-1])
    upper = raw.upper()
    if _FUTURES_MONTH.fullmatch(upper):
        return None
    alias = _ALIASES.get(upper)
    if alias:
        return alias
    return _CASEFOLD_PRODUCTS.get(upper)


def product_spec(product: str) -> DemoProduct:
    return DEMO_PRODUCTS[product]


def default_roundtrip_spread_usd_per_lot(product: str) -> float:
    spec = product_spec(product)
    if spec.category == "forex":
        return 20.0
    if product == "XAUUSD":
        return 60.0
    if product == "XAGUSD":
        return 150.0
    if spec.category == "metal":
        return 50.0
    if spec.category == "energy":
        return 50.0
    if spec.category == "index":
        return 40.0
    if spec.category == "crypto":
        return 100.0
    return 2.0


def stress_move_fraction(product: str) -> float:
    category = product_spec(product).category
    return {
        "forex": 0.01,
        "metal": 0.015,
        "energy": 0.03,
        "index": 0.02,
        "crypto": 0.06,
        "stock": 0.04,
    }[category]


def supported_demo_products() -> tuple[str, ...]:
    return tuple(DEMO_PRODUCTS)
