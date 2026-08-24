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
    "huile d olive": "huile d'olive", "huile-de-tournesol": "huile", "huilde-d-olive": "huile d'olive",
    "sel de table": "sel", "sel fin": "sel", "sel marin": "sel", "ail frais": "ail", "tête d ail": "ail",
    "noix": "noix", "noix de cajou": "noix de cajou", "lardons": "lardons", "épinards frais": "épinards",
    "poivrons": "poivron", "tortillas": "tortilla", "avocat": "avocat", "citron": "citron",
}
SEARCH_TERMS = {
    "oeuf": ["oeuf", "egg"], "poulet": ["poulet", "chicken"], "riz": ["riz", "rice"], "pâtes": ["pâtes", "pasta"],
    "champignons": ["champignons", "mushrooms"], "courgette": ["courgette", "zucchini"], "carotte": ["carotte", "carrots"],
    "parmesan": ["parmesan"], "beurre": ["beurre", "butter"], "miel": ["miel", "honey"], "sauce soja": ["sauce soja", "soy sauce"],
    "huile d'olive": ["huile d'olive", "olive oil"], "huile": ["huile", "oil"], "porc": ["porc", "pork"],
    "poisson blanc": ["poisson blanc", "white fish"], "herbes de provence": ["herbes de provence"], "pomme": ["pomme", "apple"],
    "pomme de terre": ["pomme de terre", "potato"], "brocoli": ["brocoli", "broccoli"], "sel": ["sel", "salt"],
    "poivre moulu": ["poivre", "pepper"], "ail": ["ail", "garlic"], "noix": ["noix", "walnut", "nuts"],
    "noix de cajou": ["noix de cajou", "cashew"], "lardons": ["lardons", "bacon"], "épinards": ["épinards", "spinach"],
    "poivron": ["poivron", "pepper"], "tortilla": ["tortillas", "wrap"], "avocat": ["avocat", "avocado"], "citron": ["citron", "lemon"],
}

# Baseline package prices calibrated against French supermarket observations.
# They are estimates, not live store quotes. Retailer profiles deliberately stay
# conservative and avoid the old universal 2.50 EUR fallback.
REFERENCE = {
    "oeuf": (6, "unit", 2.79), "poulet": (500, "g", 4.95), "riz": (1000, "g", 1.89), "pâtes": (500, "g", 1.25),
    "champignons": (250, "g", 1.89), "courgette": (500, "g", 1.99), "carotte": (1000, "g", 1.49), "parmesan": (200, "g", 3.29),
    "beurre": (250, "g", 2.79), "miel": (500, "g", 4.49), "sauce soja": (150, "ml", 2.29), "huile d'olive": (750, "ml", 6.99),
    "huile": (1000, "ml", 2.79), "porc": (500, "g", 5.49), "poisson blanc": (400, "g", 5.99), "herbes de provence": (20, "g", 1.19),
    "pomme": (1000, "g", 2.29), "pomme de terre": (1000, "g", 1.79), "brocoli": (500, "g", 1.99), "sel": (1000, "g", 0.89),
    "poivre moulu": (50, "g", 2.29), "ail": (2, "unit", 3.59), "noix": (125, "g", 2.25), "noix de cajou": (125, "g", 2.49),
    "lardons": (200, "g", 1.99), "épinards": (500, "g", 1.99), "poivron": (500, "g", 2.49), "tortilla": (8, "unit", 2.28),
    "avocat": (2, "unit", 1.45), "citron": (4, "unit", 1.99), "thon en boîte": (140, "g", 1.75), "quinoa": (500, "g", 3.49),
    "pois chiches": (400, "g", 0.95), "galette de sarrasin": (4, "unit", 2.50), "emmental": (200, "g", 2.99), "gingembre": (100, "g", 1.49),
    "oignon": (1000, "g", 1.49), "pain complet": (500, "g", 1.69), "saumon": (300, "g", 5.49), "cabillaud": (400, "g", 5.99),
}

RETAILER_MULTIPLIERS = {"leclerc": 0.95, "intermarche": 1.00, "carrefour": 1.03, "auchan": 1.01, "generic": 1.05}


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

    @property
    def price_per(self) -> str:
        return self.package_unit

    def packages_needed(self, quantity: float, unit: str) -> int | None:
        requested = normalise_quantity(quantity, unit); package = normalise_quantity(self.package_quantity, self.package_unit)
        if not requested or not package or requested[1] != package[1]: return None
        return max(1, math.ceil(requested[0] / package[0]))

    def purchase_cost(self, quantity: float, unit: str) -> float | None:
        count = self.packages_needed(quantity, unit)
        return round(count * self.price, 2) if count is not None else None

    def consumed_cost(self, quantity: float, unit: str) -> float | None:
        requested = normalise_quantity(quantity, unit); package = normalise_quantity(self.package_quantity, self.package_unit)
        if not requested or not package or requested[1] != package[1]: return None
        return round(self.price * requested[0] / package[0], 2)


class PriceService:
    BASE_URL = "https://prices.openfoodfacts.org/api/v1"

    def __init__(self, country_code: str = "FR", retailer: str = "leclerc"):
        self.country_code = country_code.upper(); self.retailer = retailer.lower(); self._cache: dict[str, ProductOffer] = {}

    def _fetch(self, term: str) -> list[dict]:
        try:
            response = httpx.get(f"{self.BASE_URL}/prices", params={"product_name": term, "page_size": 100}, timeout=10)
            response.raise_for_status(); data = response.json()
            return data.get("results", data.get("items", data.get("prices", [])))
        except (httpx.HTTPError, ValueError): return []

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
            return normalise_quantity(value, unit)
        reference = REFERENCE.get(canonical)
        return reference[:2] if reference else None

    def _observed_offer(self, product: str) -> ProductOffer | None:
        canonical = canonical_product(product); terms = SEARCH_TERMS.get(canonical, [canonical, product]); candidates=[]
        for term in dict.fromkeys(terms): candidates.extend(self._fetch(term))
        offers=[]; reference=REFERENCE.get(canonical)
        for item in candidates:
            if (item.get("currency") or "EUR").upper() != "EUR": continue
            location=item.get("location") or {}; country=(location.get("osm_address_country_code") or "").upper()
            if country and country != self.country_code: continue
            try: price=float(item.get("price"))
            except (TypeError,ValueError): continue
            package=self._package_from_item(item,canonical)
            if package is None or package[0] is None or package[0] <= 0 or price <= 0: continue
            package_value,package_unit=package
            if reference:
                ref=normalise_quantity(reference[0],reference[1]); observed=normalise_quantity(package_value,package_unit)
                if ref and observed and ref[1]==observed[1]:
                    ref_unit_price=reference[2]/ref[0]; observed_unit_price=price/observed[0]
                    if not (ref_unit_price*0.65 <= observed_unit_price <= ref_unit_price*1.45): continue
            offers.append((price,package_value,package_unit))
        if not offers:return None
        median_price=median(x[0] for x in offers); chosen=min(offers,key=lambda x:abs(x[0]-median_price)); confidence="high" if len(offers)>=8 else "medium" if len(offers)>=3 else "low"
        return ProductOffer(canonical,chosen[1],chosen[2],round(chosen[0],2),"Open Prices",confidence,len(offers))

    def estimate(self, product: str) -> ProductOffer:
        key=canonical_product(product)
        if key in self._cache:return self._cache[key]
        observed=self._observed_offer(product)
        if observed:
            self._cache[key]=observed; return observed
        reference=REFERENCE.get(key)
        if reference:
            multiplier=RETAILER_MULTIPLIERS.get(self.retailer,1.0)
            offer=ProductOffer(key,reference[0],reference[1],round(reference[2]*multiplier,2),f"Référence {self.retailer.capitalize()}","medium")
        else:
            # Never return the old universal 2.50 EUR placeholder. Use a conservative
            # category estimate derived from the product name and a small package.
            name=key
            if any(x in name for x in ("épice","herbe","curry","paprika","poivre")): offer=ProductOffer(key,50,"g",1.49,"Estimation catégorie","low")
            elif any(x in name for x in ("fruit","pomme","banane","orange","citron")): offer=ProductOffer(key,1,"unit",1.49,"Estimation catégorie","low")
            elif any(x in name for x in ("légume","salade","brocoli","courgette","carotte")): offer=ProductOffer(key,500,"g",2.00,"Estimation catégorie","low")
            elif any(x in name for x in ("poisson","saumon","cabillaud","thon")): offer=ProductOffer(key,300,"g",5.49,"Estimation catégorie","low")
            elif any(x in name for x in ("viande","boeuf","bœuf","poulet","porc")): offer=ProductOffer(key,500,"g",5.99,"Estimation catégorie","low")
            else: offer=ProductOffer(key,500,"g",2.19,"Estimation catégorie","very_low")
        self._cache[key]=offer; return offer

    def purchase_cost(self, product: str, quantity: float, unit: str) -> float:
        offer=self.estimate(product); return offer.purchase_cost(quantity,unit) or offer.price

    def cost(self, product: str, quantity: float, unit: str) -> float:
        offer=self.estimate(product); return offer.consumed_cost(quantity,unit) or offer.price
