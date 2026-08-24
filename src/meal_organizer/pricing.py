from dataclasses import dataclass
import math
import re
from statistics import median

import httpx


ALIASES = {
    "blanc de poulet": "poulet", "filet de poulet": "poulet", "escalope de poulet": "poulet",
    "riz blanc": "riz", "riz basmati": "riz", "oeufs": "oeuf", "œufs": "oeuf", "eggs": "oeuf",
    "champignons de paris": "champignons", "champignon de paris": "champignons",
    "pates": "pâtes", "spaghetti": "pâtes", "penne": "pâtes", "macaroni": "pâtes",
    "pommes de terre": "pomme de terre", "carottes": "carotte", "courgettes": "courgette",
    "filet mignon de porc": "porc", "sauce-soja": "sauce soja", "sauce soja": "sauce soja",
    "huile d olive": "huile d'olive", "huile-de-tournesol": "huile",
    "sel de table": "sel", "sel fin": "sel", "sel marin": "sel", "ail frais": "ail", "tête d ail": "ail",
}
SEARCH_TERMS = {
    "oeuf": ["oeuf", "egg"], "poulet": ["poulet", "chicken"], "riz": ["riz", "rice"],
    "pâtes": ["pâtes", "pasta"], "champignons": ["champignons", "mushrooms"],
    "courgette": ["courgette", "zucchini"], "carotte": ["carotte", "carrots"],
    "parmesan": ["parmesan"], "beurre": ["beurre", "butter"], "miel": ["miel", "honey"],
    "sauce soja": ["sauce soja", "soy sauce"], "huile d'olive": ["huile d'olive", "olive oil"],
    "huile": ["huile", "oil"], "porc": ["porc", "pork"], "poisson blanc": ["poisson blanc", "white fish"],
    "herbes de provence": ["herbes de provence"], "pomme": ["pomme", "apple"],
    "pomme de terre": ["pomme de terre", "potato"], "brocoli": ["brocoli", "broccoli"],
    "sel": ["sel", "salt"], "poivre moulu": ["poivre", "pepper"], "ail": ["ail", "garlic"],
}

# Conservative French supermarket reference packages. These are fallback estimates,
# not claims of live prices from a particular retailer.
REFERENCE = {
    "oeuf": (6, "unit", 2.79), "poulet": (500, "g", 5.49), "riz": (1000, "g", 2.19),
    "pâtes": (500, "g", 1.49), "champignons": (250, "g", 2.19), "courgette": (500, "g", 2.49),
    "carotte": (1000, "g", 1.49), "parmesan": (200, "g", 3.29), "beurre": (250, "g", 2.79),
    "miel": (500, "g", 4.49), "sauce soja": (150, "ml", 2.29), "huile d'olive": (750, "ml", 7.49),
    "huile": (1000, "ml", 3.49), "porc": (500, "g", 5.99), "poisson blanc": (400, "g", 6.99),
    "herbes de provence": (20, "g", 1.29), "pomme": (1000, "g", 2.29), "pomme de terre": (1000, "g", 1.79),
    "brocoli": (500, "g", 2.49), "sel": (1000, "g", 0.89), "poivre moulu": (50, "g", 2.49),
    "ail": (2, "unit", 3.59),
}


def canonical_product(name: str) -> str:
    value = re.sub(r"[^a-z0-9àâäéèêëîïôöùûüÿçœæ']+", " ", name.casefold()).strip()
    return ALIASES.get(value, value)


def normalise_quantity(quantity: float, unit: str):
    unit = unit.strip().lower()
    if unit in {"g", "gram", "grams", "gramme", "grammes"}: return quantity, "g"
    if unit in {"kg", "kilogram", "kilograms"}: return quantity * 1000, "g"
    if unit in {"ml", "millilitre", "millilitres", "milliliter", "milliliters"}: return quantity, "ml"
    if unit in {"l", "litre", "litres", "liter", "liters"}: return quantity * 1000, "ml"
    if unit in {"unit", "units", "piece", "pieces", "pcs", "pièce", "pièces"}: return quantity, "unit"
    return None


@dataclass(slots=True)
class ProductOffer:
    product: str
    package_quantity: float
    package_unit: str
    price: float
    source: str
    confidence: str
    samples: int = 0

    def packages_needed(self, quantity: float, unit: str) -> int | None:
        requested = normalise_quantity(quantity, unit)
        package = normalise_quantity(self.package_quantity, self.package_unit)
        if not requested or not package or requested[1] != package[1]: return None
        return max(1, math.ceil(requested[0] / package[0]))

    def purchase_cost(self, quantity: float, unit: str) -> float | None:
        count = self.packages_needed(quantity, unit)
        return round(count * self.price, 2) if count is not None else None

    def consumed_cost(self, quantity: float, unit: str) -> float | None:
        requested = normalise_quantity(quantity, unit)
        package = normalise_quantity(self.package_quantity, self.package_unit)
        if not requested or not package or requested[1] != package[1]: return None
        return round(self.price * requested[0] / package[0], 2)


class PriceService:
    """Estimate realistic French supermarket purchase prices.

    Open Prices observations are accepted only when their unit price is close to a
    conservative French reference range. Otherwise the reference estimate is used.
    This prevents a single atypical observation from distorting the weekly budget.
    """

    BASE_URL = "https://prices.openfoodfacts.org/api/v1"

    def __init__(self, country_code: str = "FR"):
        self.country_code = country_code.upper()
        self._cache: dict[str, ProductOffer] = {}

    def _fetch(self, term: str) -> list[dict]:
        try:
            response = httpx.get(f"{self.BASE_URL}/prices", params={"product_name": term, "page_size": 100}, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("results", data.get("items", data.get("prices", [])))
        except (httpx.HTTPError, ValueError):
            return []

    def _package_from_item(self, item: dict, canonical: str):
        product = item.get("product") or {}
        for quantity, unit in ((product.get("product_quantity"), product.get("product_quantity_unit")), (item.get("product_quantity"), item.get("product_quantity_unit"))):
            try:
                if quantity and unit:
                    parsed = normalise_quantity(float(quantity), str(unit))
                    if parsed: return parsed
            except (TypeError, ValueError): pass
        text = " ".join(str(item.get(k, "")) for k in ("product_name", "product_code", "name")).lower()
        match = re.search(r"(?:x\s*)?(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|l)", text)
        if match:
            value, unit = float(match.group(1).replace(",", ".")), match.group(2)
            if unit == "cl": value, unit = value * 10, "ml"
            parsed = normalise_quantity(value, unit)
            if parsed: return parsed
        return REFERENCE.get(canonical, (None, None, None))[:2]

    def _observed_offer(self, product: str) -> ProductOffer | None:
        canonical = canonical_product(product)
        terms = SEARCH_TERMS.get(canonical, [canonical, product])
        candidates = []
        for term in dict.fromkeys(terms): candidates.extend(self._fetch(term))
        offers = []
        reference = REFERENCE.get(canonical)
        for item in candidates:
            if (item.get("currency") or "EUR").upper() != "EUR": continue
            location = item.get("location") or {}
            country = (location.get("osm_address_country_code") or "").upper()
            if country and country != self.country_code: continue
            try: price = float(item.get("price"))
            except (TypeError, ValueError): continue
            package = self._package_from_item(item, canonical)
            if package is None or package[0] is None or package[0] <= 0 or price <= 0:continue
            package_value, package_unit = package
            if reference:
                ref_value, ref_unit, ref_price = reference
                ref = normalise_quantity(ref_value, ref_unit); observed = normalise_quantity(package_value, package_unit)
                if ref and observed and ref[1] == observed[1]:
                    ref_unit_price = ref_price / ref[0]; observed_unit_price = price / observed[0]
                    # Keep observations within a deliberately tight band around the French reference.
                    if not (ref_unit_price * 0.55 <= observed_unit_price <= ref_unit_price * 1.75): continue
            offers.append((price, package_value, package_unit))
        if not offers: return None
        median_price = median(x[0] for x in offers)
        chosen = min(offers, key=lambda x: abs(x[0] - median_price))
        confidence = "high" if len(offers) >= 8 else "medium" if len(offers) >= 3 else "low"
        return ProductOffer(canonical, chosen[1], chosen[2], round(chosen[0], 2), "Open Prices", confidence, len(offers))

    def estimate(self, product: str) -> ProductOffer:
        key = canonical_product(product)
        if key in self._cache: return self._cache[key]
        observed = self._observed_offer(product)
        if observed:
            self._cache[key] = observed
            return observed
        reference = REFERENCE.get(key)
        if reference:
            offer = ProductOffer(key, reference[0], reference[1], reference[2], "Estimation France", "medium")
        else:
            offer = ProductOffer(key, 1, "unit", 2.50, "Estimation générique", "very_low")
        self._cache[key] = offer
        return offer

    def purchase_cost(self, product: str, quantity: float, unit: str) -> float:
        offer = self.estimate(product)
        return offer.purchase_cost(quantity, unit) or offer.price

    def cost(self, product: str, quantity: float, unit: str) -> float:
        offer = self.estimate(product)
        return offer.consumed_cost(quantity, unit) or offer.price
