from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re

import httpx

ALIASES = {
    "blanc de poulet": "poulet", "filet de poulet": "poulet", "escalope de poulet": "poulet",
    "riz blanc": "riz", "riz basmati": "riz", "oeufs": "oeuf", "eggs": "egg",
    "champignons de paris": "champignons", "champignon de paris": "champignons",
    "pates": "pâtes", "spaghetti": "pâtes", "penne": "pâtes", "macaroni": "pâtes",
}
SEARCH_TERMS = {
    "oeuf": ["oeuf", "eggs"], "egg": ["oeuf", "eggs"], "poulet": ["poulet", "chicken"],
    "riz": ["riz", "rice"], "pâtes": ["pâtes", "pasta"], "champignons": ["champignons", "mushrooms"],
    "courgette": ["courgette", "zucchini"], "carotte": ["carotte", "carrots"], "parmesan": ["parmesan"],
    "beurre": ["beurre", "butter"], "miel": ["miel", "honey"], "sauce soja": ["sauce soja", "soy sauce"],
    "huile": ["huile", "oil"], "porc": ["porc", "pork"], "poisson blanc": ["poisson blanc", "white fish"],
    "herbes de provence": ["herbes de provence"],
}

def canonical_product(name: str) -> str:
    value = re.sub(r"[^a-z0-9àâäéèêëîïôöùûüÿçœæ]+", " ", name.casefold()).strip()
    return ALIASES.get(value, value)

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
        if requested is None: return None
        value, base_unit = requested
        per = (self.price_per or "UNIT").upper()
        if per in {"KG", "KILOGRAM"} and base_unit == "g": return round(self.price * value / 1000, 2)
        if per in {"G", "GRAM"} and base_unit == "g": return round(self.price * value, 2)
        if per in {"100G", "100_G"} and base_unit == "g": return round(self.price * value / 100, 2)
        if per in {"L", "LITER", "LITRE"} and base_unit == "ml": return round(self.price * value / 1000, 2)
        if per in {"100ML", "100_ML"} and base_unit == "ml": return round(self.price * value / 100, 2)
        if per == "UNIT" and base_unit == "unit":
            if self.package_quantity and self.package_unit == "unit": return round(self.price * value / self.package_quantity, 2)
            return round(self.price * value, 2)
        if self.package_quantity and self.package_unit == base_unit: return round(self.price * value / self.package_quantity, 2)
        return None

    def purchase_cost(self, quantity: float, unit: str) -> float | None:
        requested = _normalise_quantity(quantity, unit)
        if requested and self.package_quantity and self.package_unit == requested[1]:
            return round(math.ceil(requested[0] / self.package_quantity) * self.price, 2)
        return self.cost_for(quantity, unit)

def _normalise_quantity(quantity: float, unit: str):
    unit = unit.strip().lower()
    if unit in {"g", "gram", "grams", "gramme", "grammes"}: return quantity, "g"
    if unit in {"kg", "kilogram", "kilograms"}: return quantity * 1000, "g"
    if unit in {"ml", "millilitre", "millilitres", "milliliter", "milliliters"}: return quantity, "ml"
    if unit in {"l", "litre", "litres", "liter", "liters"}: return quantity * 1000, "ml"
    if unit in {"unit", "units", "piece", "pieces", "pcs", "pièce", "pièces"}: return quantity, "unit"
    return None

def _parse_package(product: dict, product_name: str):
    nested = product.get("product") or {}
    value, unit = nested.get("product_quantity"), nested.get("product_quantity_unit")
    try:
        if value and unit: return float(value), str(unit).lower()
    except (TypeError, ValueError): pass
    name = canonical_product(product_name)
    defaults = [
        (("oeuf", "egg"), 6, "unit"), (("pâte", "pasta"), 500, "g"), (("riz", "rice"), 1000, "g"),
        (("parmesan",), 200, "g"), (("champignon", "mushroom"), 250, "g"), (("poulet", "chicken"), 500, "g"),
        (("thon", "tuna"), 140, "g"), (("beurre", "butter"), 250, "g"), (("miel", "honey"), 500, "g"),
        (("sauce soja", "soy sauce"), 150, "ml"), (("huile", "oil"), 1000, "ml"),
    ]
    for keywords, package_value, package_unit in defaults:
        if any(keyword in name for keyword in keywords): return package_value, package_unit
    return None, None

def _plausible(product: str, price: float, price_per: str | None, package_quantity: float | None, package_unit: str | None) -> bool:
    name = canonical_product(product); per = (price_per or "UNIT").upper()
    if "oeuf" in name or name == "egg":
        if per == "UNIT" and package_quantity and package_unit == "unit": return price / package_quantity <= 1.0
        if per == "UNIT": return price <= 1.0
    limits = {"riz": 8, "pâtes": 8, "poulet": 25, "porc": 22, "boeuf": 35, "bœuf": 35, "lentille": 10}
    for word, limit in limits.items():
        if word in name and per in {"KG", "KILOGRAM"}: return price <= limit
    return 0 < price <= 100

class OpenPricesProvider:
    BASE_URL = "https://prices.openfoodfacts.org/api/v1"
    def __init__(self, country_code: str = "FR"): self.country_code = country_code.upper()

    def _fetch(self, term: str) -> list[dict]:
        try:
            response = httpx.get(f"{self.BASE_URL}/prices", params={"product_name": term, "page_size": 100}, timeout=15)
            response.raise_for_status(); data = response.json()
            return data.get("results", data.get("items", data.get("prices", [])))
        except (httpx.HTTPError, ValueError): return []

    def estimate(self, product: str) -> PriceEstimate | None:
        canonical = canonical_product(product)
        raw: list[dict] = []
        for term in dict.fromkeys(SEARCH_TERMS.get(canonical, [canonical, product])): raw.extend(self._fetch(term))
        prices = []
        for item in raw:
            location = item.get("location") or {}; country = (location.get("osm_address_country_code") or "").upper()
            if country and country != self.country_code: continue
            if (item.get("currency") or "EUR").upper() != "EUR": continue
            try: value = float(item.get("price"))
            except (TypeError, ValueError): continue
            package_quantity, package_unit = _parse_package(item, canonical)
            if not _plausible(canonical, value, item.get("price_per"), package_quantity, package_unit): continue
            prices.append((value, item, package_quantity, package_unit))
        if not prices: return None
        values = sorted(x[0] for x in prices); median = values[len(values) // 2]
        latest = min(prices, key=lambda x: abs(x[0] - median))[1]
        package_quantity, package_unit = _parse_package(latest, canonical)
        confidence = "high" if len(values) >= 8 else "medium" if len(values) >= 3 else "low"
        return PriceEstimate(product=canonical, price=round(median, 2), currency="EUR", source="Open Prices", confidence=confidence, observed_at=latest.get("date") or datetime.now(timezone.utc).date().isoformat(), samples=len(values), price_per=latest.get("price_per"), package_quantity=package_quantity, package_unit=package_unit)

class PriceService:
    def __init__(self, country_code: str = "FR"):
        self.open_prices = OpenPricesProvider(country_code); self._cache: dict[str, PriceEstimate | None] = {}
    def estimate(self, product: str):
        key = canonical_product(product)
        if key not in self._cache: self._cache[key] = self.open_prices.estimate(product)
        return self._cache[key]
    def cost(self, product: str, quantity: float, unit: str):
        estimate = self.estimate(product); return estimate.cost_for(quantity, unit) if estimate else None
    def purchase_cost(self, product: str, quantity: float, unit: str):
        estimate = self.estimate(product); return estimate.purchase_cost(quantity, unit) if estimate else None
