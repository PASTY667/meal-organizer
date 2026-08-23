from dataclasses import dataclass
from datetime import datetime, timezone
import math

import httpx


@dataclass(slots=True)
class PriceEstimate:
    product: str
    price: float
    currency: str
    source: str
    confidence: str
    observed_at: str | None = None
    samples: int = 0
    price_per: str | None = None
    package_quantity: float | None = None
    package_unit: str | None = None

    def cost_for(self, quantity: float, unit: str) -> float | None:
        requested = _normalise_quantity(quantity, unit)
        if requested is None:
            return None
        base_value, base_unit = requested
        per = (self.price_per or "UNIT").upper()
        if per in {"KG", "KILOGRAM"} and base_unit == "g": return round(self.price * base_value / 1000, 2)
        if per in {"G", "GRAM"} and base_unit == "g": return round(self.price * base_value, 2)
        if per in {"100G", "100_G"} and base_unit == "g": return round(self.price * base_value / 100, 2)
        if per in {"L", "LITER", "LITRE"} and base_unit == "ml": return round(self.price * base_value / 1000, 2)
        if per in {"100ML", "100_ML"} and base_unit == "ml": return round(self.price * base_value / 100, 2)
        if per == "UNIT" and base_unit == "unit": return round(self.price * base_value, 2)
        if self.package_quantity and self.package_unit == base_unit: return round(self.price * base_value / self.package_quantity, 2)
        return None

    def purchase_cost(self, quantity: float, unit: str) -> float | None:
        requested = _normalise_quantity(quantity, unit)
        if requested and self.package_quantity and self.package_unit == requested[1]:
            return round(math.ceil(requested[0] / self.package_quantity) * self.price, 2)
        return self.cost_for(quantity, unit)


def _normalise_quantity(quantity: float, unit: str) -> tuple[float, str] | None:
    unit = unit.strip().lower()
    if unit in {"g", "gram", "grams", "gramme", "grammes"}: return quantity, "g"
    if unit in {"kg", "kilogram", "kilograms"}: return quantity * 1000, "g"
    if unit in {"ml", "millilitre", "millilitres", "milliliter", "milliliters"}: return quantity, "ml"
    if unit in {"l", "litre", "litres", "liter", "liters"}: return quantity * 1000, "ml"
    if unit in {"unit", "units", "piece", "pieces", "pcs", "pièce", "pièces"}: return quantity, "unit"
    return None


def _parse_package(product: dict) -> tuple[float | None, str | None]:
    nested = product.get("product") or {}
    value = nested.get("product_quantity"); unit = nested.get("product_quantity_unit")
    try: return (float(value), str(unit).lower()) if value and unit else (None, None)
    except (TypeError, ValueError): return None, None


class OpenPricesProvider:
    BASE_URL = "https://prices.openfoodfacts.org/api/v1"

    def __init__(self, country_code: str = "FR"):
        self.country_code = country_code.upper()

    def estimate(self, product: str) -> PriceEstimate | None:
        try:
            response = httpx.get(f"{self.BASE_URL}/prices", params={"product_name": product, "page_size": 100}, timeout=15)
            response.raise_for_status(); data = response.json()
        except (httpx.HTTPError, ValueError): return None
        items = data.get("results", data.get("items", data.get("prices", [])))
        prices: list[tuple[float, dict]] = []
        for item in items:
            location = item.get("location") or {}; country = (location.get("osm_address_country_code") or "").upper()
            if country and country != self.country_code: continue
            if (item.get("currency") or "EUR") != "EUR": continue
            try: value = float(item.get("price"))
            except (TypeError, ValueError): continue
            if value >= 0: prices.append((value, item))
        if not prices: return None
        values = sorted(value for value, _ in prices); median = values[len(values) // 2]
        latest = max(prices, key=lambda x: x[1].get("date", ""))[1]
        package_quantity, package_unit = _parse_package(latest)
        confidence = "high" if len(values) >= 8 else "medium" if len(values) >= 3 else "low"
        return PriceEstimate(product=product, price=round(median, 2), currency=latest.get("currency") or "EUR", source="Open Prices", confidence=confidence, observed_at=latest.get("date") or datetime.now(timezone.utc).date().isoformat(), samples=len(values), price_per=latest.get("price_per"), package_quantity=package_quantity, package_unit=package_unit)


class PriceService:
    def __init__(self, country_code: str = "FR"):
        self.open_prices = OpenPricesProvider(country_code)
        self._cache: dict[str, PriceEstimate | None] = {}

    def estimate(self, product: str) -> PriceEstimate | None:
        key = product.strip().casefold()
        if key not in self._cache: self._cache[key] = self.open_prices.estimate(product)
        return self._cache[key]

    def cost(self, product: str, quantity: float, unit: str) -> float | None:
        estimate = self.estimate(product)
        return estimate.cost_for(quantity, unit) if estimate else None

    def purchase_cost(self, product: str, quantity: float, unit: str) -> float | None:
        estimate = self.estimate(product)
        return estimate.purchase_cost(quantity, unit) if estimate else None
