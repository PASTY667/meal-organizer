import json

from pydantic import TypeAdapter

from .config import UserConfig
from .db import InventoryItem
from .llm import LLMProvider, LLMRequest
from .models import MealIngredient, MealPlan, PlannedMeal, Recipe
from .pricing import PriceService

TEXT = {
    "fr": {
        "system": """Tu es le moteur de planification de Meal Organizer. Réponds en français.
Tu dois construire la semaine comme un problème global d'optimisation, pas comme une suite de repas indépendants.
Commence par raisonner sur le budget total, le stock disponible, les achats nécessaires, la réutilisation des ingrédients, les portions et la variété, puis produis le plan final.
Allergies = contraintes absolues. Les aliments refusés ne doivent jamais apparaître. N'utilise que l'équipement fourni.
Planifie exactement 14 repas : déjeuner et dîner pour chacun des 7 jours.
Pour chaque repas, utilise des portions normales et rassasiantes pour le nombre de personnes demandé : environ 80-120 g de féculents secs, 120-180 g de viande/poisson, 2-3 œufs et une portion généreuse de légumes lorsque cela correspond au plat.
Privilégie des ingrédients polyvalents pouvant être utilisés plusieurs fois dans la semaine afin de réduire le nombre de produits achetés et le gaspillage.
Le stock est utilisé en priorité, mais tu peux et dois proposer des achats lorsque cela améliore le menu ou est nécessaire.
Ne rédige pas les recettes complètes. Donne uniquement nom, description et ingrédients avec quantités.
Ne mets aucun prix dans les repas : l'application calcule les achats à partir de sources externes.
Si la recherche web est disponible, utilise-la pour trouver des idées de recettes crédibles et adaptées, mais ne copie pas une recette complète.
Retourne uniquement le JSON correspondant au schéma fourni.""",
        "recipe": "Génère une recette détaillée en français à partir du repas choisi, du stock et de la liste de courses. Respecte strictement allergies, aliments refusés, équipement et nombre de portions. Si la recherche web est disponible, recherche une ou plusieurs recettes crédibles puis adapte-les. Donne des étapes numérotées claires, simples et réalisables par un étudiant, avec les quantités utiles au moment de cuisiner.",
        "question": "Réponds en français à la question de l'utilisateur sur ce repas sans modifier le plan.",
        "replace": "Remplace uniquement le repas demandé. Prends en compte toute la semaine, le budget restant, le stock et les achats déjà prévus. Retourne uniquement un PlannedMeal JSON.",
    },
    "en": {
        "system": """You are the Meal Organizer planning engine. Respond in English.
Treat the week as one global optimization problem, not as independent meals.
First reason about the total budget, current inventory, required purchases, ingredient reuse, portions and variety, then produce the final plan.
Allergies are hard constraints. Disliked foods must never appear. Only use the provided equipment.
Plan exactly 14 meals: lunch and dinner for each of 7 days.
Use normal satisfying portions for the requested servings: roughly 80-120 g dry starch, 120-180 g meat/fish, 2-3 eggs and a generous vegetable portion where appropriate.
Prefer versatile ingredients that can be reused during the week to reduce the number of purchased products and waste.
Use inventory first, but propose purchases whenever needed or useful.
Do not write full recipes. Give only name, description and ingredient quantities.
Do not put prices in meals: the application calculates purchases from external sources.
If web search is available, use it to find credible recipe ideas and adapt them without copying a full recipe.
Return only JSON matching the supplied schema.""",
        "recipe": "Generate a detailed recipe in English from the selected meal, inventory and shopping list. Strictly respect allergies, disliked foods, equipment and servings. If web research is available, search for credible recipes and adapt them. Give clear numbered steps suitable for a student, including useful quantities while cooking.",
        "question": "Answer the user's question about this meal in English without changing the plan.",
        "replace": "Replace only the requested meal. Consider the whole week, remaining budget, inventory and planned purchases. Return only a PlannedMeal JSON object.",
    },
}


def _inventory_payload(inventory: list[InventoryItem]) -> list[dict]:
    return [{"name": i.name, "quantity": i.quantity, "unit": i.unit, "location": i.location} for i in inventory]


def _parse_json(response: str):
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return cleaned


def build_plan_request(config: UserConfig, inventory: list[InventoryItem]) -> LLMRequest:
    payload = {
        "servings": config.servings,
        "weekly_budget_eur": config.weekly_budget,
        "language": config.language,
        "allergies": config.allergies,
        "dislikes": config.dislikes,
        "equipment": config.equipment,
        "inventory": _inventory_payload(inventory),
        "planning_goal": "Design the complete week first, then express the 14 selected meals. Optimize the shopping basket globally.",
        "required_output_schema": MealPlan.model_json_schema(),
    }
    return LLMRequest(system=TEXT[config.language]["system"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)


def _normalise(value: float, unit: str) -> tuple[float, str]:
    unit = unit.lower().strip()
    if unit == "kg": return value * 1000, "g"
    if unit in {"g", "gram", "grams", "gramme", "grammes"}: return value, "g"
    if unit == "l": return value * 1000, "ml"
    if unit in {"ml", "millilitre", "millilitres", "milliliter", "milliliters"}: return value, "ml"
    if unit in {"unit", "units", "piece", "pieces", "pcs", "pièce", "pièces"}: return value, "unit"
    return value, "unit"


def _inventory_quantity(name: str, unit: str, inventory: list[InventoryItem]) -> float:
    target = _normalise(0, unit)[1]; total = 0.0
    for item in inventory:
        if item.name.casefold() != name.casefold(): continue
        value, item_unit = _normalise(item.quantity, item.unit)
        if item_unit == target: total += value
    return total


def build_shopping_list(plan: MealPlan, inventory: list[InventoryItem], pricing: PriceService | None = None) -> list[MealIngredient]:
    grouped: dict[tuple[str, str], dict[str, float | str]] = {}
    for meal in plan.meals:
        for ingredient in meal.ingredients:
            quantity, unit = _normalise(ingredient.quantity, ingredient.unit)
            key = (ingredient.name.casefold(), unit)
            if key not in grouped: grouped[key] = {"name": ingredient.name, "quantity": 0.0, "unit": unit}
            grouped[key]["quantity"] = float(grouped[key]["quantity"]) + quantity
    result: list[MealIngredient] = []
    pricing = pricing or PriceService()
    for item in grouped.values():
        name = str(item["name"]); unit = str(item["unit"]); required = float(item["quantity"])
        missing = max(0.0, required - _inventory_quantity(name, unit, inventory))
        if missing <= 0: continue
        estimate = pricing.estimate(name)
        result.append(MealIngredient(name=name, quantity=round(missing, 2), unit=unit, estimated_cost=estimate.purchase_cost(missing, unit) if estimate else None))
    return result


def price_plan(plan: MealPlan, config: UserConfig, inventory: list[InventoryItem], enforce_budget: bool = True, pricing: PriceService | None = None) -> MealPlan:
    pricing = pricing or PriceService()
    for meal in plan.meals:
        meal_cost = 0.0
        for ingredient in meal.ingredients:
            required_value, required_unit = _normalise(ingredient.quantity, ingredient.unit)
            estimate = pricing.estimate(ingredient.name)
            ingredient.estimated_cost = estimate.cost_for(required_value, required_unit) if estimate else None
            if ingredient.estimated_cost is not None: meal_cost += ingredient.estimated_cost
        meal.estimated_cost = round(meal_cost, 2) if meal_cost else None
    shopping = build_shopping_list(plan, inventory, pricing)
    plan.shopping_cost = round(sum(item.estimated_cost or 0 for item in shopping), 2)
    plan.total_food_cost = round(sum(meal.estimated_cost or 0 for meal in plan.meals), 2)
    if enforce_budget and plan.shopping_cost > config.weekly_budget + 0.01:
        raise ValueError(f"Plan exceeds weekly shopping budget: {plan.shopping_cost:.2f} > {config.weekly_budget:.2f} EUR")
    return plan


def generate_plan(provider: LLMProvider, config: UserConfig, inventory: list[InventoryItem]) -> MealPlan:
    plan = MealPlan.model_validate_json(_parse_json(provider.generate(build_plan_request(config, inventory))))
    if len(plan.meals) != 14: raise ValueError(f"Expected 14 meals, received {len(plan.meals)}")
    return price_plan(plan, config, inventory, enforce_budget=False)


def build_recipe_request(config: UserConfig, meal: PlannedMeal, inventory: list[InventoryItem], shopping: list[MealIngredient]) -> LLMRequest:
    payload = {"servings": config.servings, "meal": meal.model_dump(), "inventory": _inventory_payload(inventory), "shopping_list": [i.model_dump() for i in shopping], "schema": Recipe.model_json_schema()}
    return LLMRequest(system=TEXT[config.language]["recipe"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)


def generate_recipe(provider: LLMProvider, config: UserConfig, meal: PlannedMeal, inventory: list[InventoryItem], shopping: list[MealIngredient]) -> Recipe:
    return Recipe.model_validate_json(_parse_json(provider.generate(build_recipe_request(config, meal, inventory, shopping))))


def build_question_request(config: UserConfig, meal: PlannedMeal, question: str) -> LLMRequest:
    return LLMRequest(system=TEXT[config.language]["question"], prompt=json.dumps({"meal": meal.model_dump(), "question": question}, ensure_ascii=False), web_search=config.llm.web_search)


def replace_meal(provider: LLMProvider, config: UserConfig, meal: PlannedMeal, inventory: list[InventoryItem], reason: str) -> PlannedMeal:
    payload = {"meal_to_replace": meal.model_dump(), "reason": reason, "servings": config.servings, "budget_eur": config.weekly_budget, "allergies": config.allergies, "dislikes": config.dislikes, "equipment": config.equipment, "inventory": _inventory_payload(inventory), "schema": PlannedMeal.model_json_schema()}
    request = LLMRequest(system=TEXT[config.language]["replace"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)
    return PlannedMeal.model_validate_json(_parse_json(provider.generate(request)))
