from dataclasses import dataclass
from datetime import datetime, timezone

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


class OpenPricesProvider:
    """Read-only adapter for the Open Prices REST API."""

    BASE_URL = "https://prices.openfoodfacts.org/api/v1"

    def __init__(self, country_code: str = "FR"):
        self.country_code = country_code.upper()

    def estimate(self, product: str) -> PriceEstimate | None:
        try:
            response = httpx.get(
                f"{self.BASE_URL}/prices",
                params={"product_name": product, "page_size": 100},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        items = data.get("results", data.get("items", data.get("prices", [])))
        prices: list[tuple[float, dict]] = []
        for item in items:
            location = item.get("location") or {}
            item_country = (location.get("osm_address_country_code") or "").upper()
            if item_country and item_country != self.country_code:
                continue
            currency = item.get("currency")
            if currency and currency != "EUR":
                continue
            try:
                value = float(item.get("price"))
            except (TypeError, ValueError):
                continue
            if value >= 0:
                prices.append((value, item))

        if not prices:
            return None

        prices.sort(key=lambda x: x[0])
        values = [value for value, _ in prices]
        median = values[len(values) // 2]
        latest = max(prices, key=lambda x: x[1].get("date", ""))[1]
        confidence = "high" if len(values) >= 8 else "medium" if len(values) >= 3 else "low"
        return PriceEstimate(
            product=product,
            price=round(median, 2),
            currency=latest.get("currency") or "EUR",
            source="Open Prices",
            confidence=confidence,
            observed_at=latest.get("date") or datetime.now(timezone.utc).date().isoformat(),
            samples=len(values),
        )


class PriceService:
    def __init__(self, country_code: str = "FR"):
        self.open_prices = OpenPricesProvider(country_code)

    def estimate(self, product: str) -> PriceEstimate | None:
        return self.open_prices.estimate(product)
