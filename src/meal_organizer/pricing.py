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
    """Adapter for Open Prices. API details are isolated here so the source can evolve safely."""

    BASE_URL = "https://prices.openfoodfacts.org/api/v1"

    def __init__(self, location: str = "FR"):
        self.location = location

    def estimate(self, product: str) -> PriceEstimate | None:
        try:
            response = httpx.get(
                f"{self.BASE_URL}/prices",
                params={"product_name": product, "country_code": self.location, "page_size": 20},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        prices = []
        for item in data.get("items", data.get("prices", [])):
            value = item.get("price")
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                prices.append((value, item))

        if not prices:
            return None

        prices.sort(key=lambda x: x[0])
        values = [value for value, _ in prices]
        median = values[len(values) // 2]
        latest = max((item for _, item in prices), key=lambda x: x.get("date", ""), default={})
        confidence = "high" if len(values) >= 8 else "medium" if len(values) >= 3 else "low"
        return PriceEstimate(
            product=product,
            price=round(median, 2),
            currency=latest.get("currency", "EUR"),
            source="Open Prices",
            confidence=confidence,
            observed_at=latest.get("date") or datetime.now(timezone.utc).date().isoformat(),
            samples=len(values),
        )


class PriceService:
    def __init__(self, location: str = "FR"):
        self.open_prices = OpenPricesProvider(location)

    def estimate(self, product: str) -> PriceEstimate | None:
        return self.open_prices.estimate(product)
