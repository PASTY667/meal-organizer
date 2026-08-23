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
Les allergies sont des contraintes absolues. Les aliments refusés ne doivent jamais apparaître.
N'utilise que l'équipement fourni. Utilise le stock quand c'est pertinent, mais propose aussi des achats.
Construis progressivement une semaine de 7 jours avec déjeuner et dîner.
Pour chaque créneau demandé, propose exactement 2 plats différents et réalistes.
Les quantités sont pour le nombre de personnes indiqué. Pour un adulte, vise des portions normales et rassasiantes : environ 80-120 g de féculents secs, 120-180 g de viande/poisson, 2-3 œufs et une portion généreuse de légumes selon le plat.
Évite les portions manifestement trop petites. Réutilise intelligemment les ingrédients sans faire manger exactement le même plat plusieurs fois.
Ne rédige pas les recettes complètes. Donne nom, description et ingrédients avec quantités.
Les coûts sont calculés par l'application à partir des prix externes. Retourne uniquement le JSON demandé.""",
        "recipe": "Génère une recette détaillée en français à partir du repas planifié, du stock et de la liste de courses. Respecte strictement allergies, aliments refusés et équipement. Donne des étapes numérotées simples, adaptées à un étudiant. Si la recherche web est disponible, privilégie des recettes réelles et crédibles et indique les sources utilisées.",
        "question": "Réponds en français à la question de l'utilisateur sur ce repas sans modifier le plan.",
        "recipe_question": "Réponds en français à la question de l'utilisateur sur cette recette. Sois pratique et précis.",
        "replace": "Remplace uniquement le repas demandé. Respecte strictement les contraintes, les portions normales, le budget et le stock. Retourne uniquement un PlannedMeal JSON.",
    },
    "en": {
        "system": """You are the Meal Organizer planning engine. Respond in English.
Allergies are hard constraints. Disliked foods must never appear.
Only use the provided equipment. Use inventory when useful, but also propose purchases.
Build a 7-day week progressively with lunch and dinner.
For each requested slot, propose exactly 2 different, realistic dishes.
Quantities are for the requested number of servings. For an adult, use normal satisfying portions: roughly 80-120 g dry starch, 120-180 g meat/fish, 2-3 eggs and a generous vegetable portion where appropriate.
Avoid obviously tiny portions. Reuse ingredients intelligently without repeating exactly the same dish too often.
Do not write full recipes. Give name, description and ingredient quantities.
Costs are calculated by the application from external price data. Return only the requested JSON.""",
        "recipe": "Generate a detailed recipe in English from the planned meal, inventory and shopping list. Strictly respect allergies, disliked foods and equipment. Give simple numbered steps suitable for a student. If web research is available, prefer real, credible recipes and include sources.",
        "question": "Answer the user's question about this meal in English without changing the plan.",
        "recipe_question": "Answer the user's question about this recipe in English. Be practical and precise.",
        "replace": "Replace only the requested meal. Strictly respect constraints, normal portions, budget and inventory. Return only a PlannedMeal JSON object.",
    },
}


def _inventory_payload(inventory: list[InventoryItem]) -> list[dict]:
    return [{"name": item.name, "quantity": item.quantity, "unit": item.unit, "location": item.location} for item in inventory]


def _parse_json(response: str):
    cleaned = response.strip()
    if cleaned.startswith("```"): cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return cleaned


def build_plan_request(config: UserConfig, inventory: list[InventoryItem]) -> LLMRequest:
    payload = {"servings": config.servings, "weekly_budget_eur": config.weekly_budget, "language": config.language, "allergies": config.allergies, "dislikes": config.dislikes, "equipment": config.equipment, "inventory": _inventory_payload(inventory), "required_output_schema": MealPlan.model_json_schema()}
    return LLMRequest(system=TEXT[config.language]["system"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True)


def build_day_options_request(config: UserConfig, inventory: list[InventoryItem], existing: list[PlannedMeal], day: str) -> LLMRequest:
    schema = TypeAdapter(list[PlannedMeal]).json_schema()
    payload = {"day": day, "servings": config.servings, "weekly_budget_eur": config.weekly_budget, "allergies": config.allergies, "dislikes": config.dislikes, "equipment": config.equipment, "inventory": _inventory_payload(inventory), "already_selected_meals": [meal.model_dump() for meal in existing], "required_output_schema": schema, "rules": {"options": 4, "two_lunches": 2, "two_dinners": 2, "normal_portions": True}}
    return LLMRequest(system=TEXT[config.language]["system"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)


def generate_day_options(provider: LLMProvider, config: UserConfig, inventory: list[InventoryItem], existing: list[PlannedMeal], day: str) -> list[PlannedMeal]:
    options = TypeAdapter(list[PlannedMeal]).validate_json(_parse_json(provider.generate(build_day_options_request(config, inventory, existing, day))))
    if len(options) != 4: raise ValueError(f"Expected 4 options for {day}, received {len(options)}")
    lunches = [m for m in options if m.meal.casefold() in {"déjeuner", "dejeuner", "lunch"}]
    dinners = [m for m in options if m.meal.casefold() in {"dîner", "diner", "dinner"}]
    if len(lunches) != 2 or len(dinners) != 2: raise ValueError(f"The model did not return 2 lunch and 2 dinner options for {day}")
    return options


def _normalise(value: float, unit: str) -> tuple[float, str]:
    unit = unit.lower().strip()
    if unit == "kg": return value * 1000, "g"
    if unit in {"g", "gram", "grams", "gramme", "grammes"}: return value, "g"
    if unit == "l": return value * 1000, "ml"
    if unit in {"ml", "millilitre", "millilitres", "milliliter", "milliliters"}: return value, "ml"
    return value, "unit"


def _inventory_quantity(name: str, unit: str, inventory: list[InventoryItem]) -> float:
    target = _normalise(0, unit)[1]; total = 0.0
    for item in inventory:
        if item.name.casefold() != name.casefold(): continue
        item_value, item_unit = _normalise(item.quantity, item.unit)
        if item_unit == target: total += item_value
    return total


def build_shopping_list(plan: MealPlan, inventory: list[InventoryItem], pricing: PriceService | None = None) -> list[MealIngredient]:
    grouped: dict[tuple[str, str], dict[str, float | str]] = {}
    for meal in plan.meals:
        for ingredient in meal.ingredients:
            quantity, unit = _normalise(ingredient.quantity, ingredient.unit); key = (ingredient.name.casefold(), unit)
            if key not in grouped: grouped[key] = {"name": ingredient.name, "quantity": 0.0, "unit": unit}
            grouped[key]["quantity"] = float(grouped[key]["quantity"]) + quantity
    result: list[MealIngredient] = []; pricing = pricing or PriceService()
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
            required_value, required_unit = _normalise(ingredient.quantity, ingredient.unit); estimate = pricing.estimate(ingredient.name)
            ingredient.estimated_cost = estimate.cost_for(required_value, required_unit) if estimate else None
            if ingredient.estimated_cost is not None: meal_cost += ingredient.estimated_cost
        meal.estimated_cost = round(meal_cost, 2) if meal_cost else None
    shopping = build_shopping_list(plan, inventory, pricing)
    plan.shopping_cost = round(sum(item.estimated_cost or 0 for item in shopping), 2); plan.total_food_cost = round(sum(meal.estimated_cost or 0 for meal in plan.meals), 2)
    if enforce_budget and plan.shopping_cost > config.weekly_budget + 0.01: raise ValueError(f"Plan exceeds weekly shopping budget: {plan.shopping_cost:.2f} > {config.weekly_budget:.2f} EUR")
    return plan


def generate_plan(provider: LLMProvider, config: UserConfig, inventory: list[InventoryItem]) -> MealPlan:
    plan = MealPlan.model_validate_json(_parse_json(provider.generate(build_plan_request(config, inventory))))
    if len(plan.meals) != 14: raise ValueError(f"Expected 14 meals, received {len(plan.meals)}")
    return price_plan(plan, config, inventory)


def build_recipe_request(config: UserConfig, meal: PlannedMeal, inventory: list[InventoryItem], shopping: list[MealIngredient]) -> LLMRequest:
    payload = {"servings": config.servings, "meal": meal.model_dump(), "inventory": _inventory_payload(inventory), "shopping_list": [item.model_dump() for item in shopping], "schema": Recipe.model_json_schema()}
    return LLMRequest(system=TEXT[config.language]["recipe"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)


def generate_recipe(provider: LLMProvider, config: UserConfig, meal: PlannedMeal, inventory: list[InventoryItem], shopping: list[MealIngredient]) -> Recipe:
    return Recipe.model_validate_json(_parse_json(provider.generate(build_recipe_request(config, meal, inventory, shopping))))


def build_question_request(config: UserConfig, meal: PlannedMeal, question: str) -> LLMRequest:
    return LLMRequest(system=TEXT[config.language]["question"], prompt=json.dumps({"meal": meal.model_dump(), "question": question}, ensure_ascii=False), web_search=config.llm.web_search)


def build_recipe_question_request(config: UserConfig, recipe: Recipe, question: str) -> LLMRequest:
    return LLMRequest(system=TEXT[config.language]["recipe_question"], prompt=json.dumps({"recipe": recipe.model_dump(), "question": question}, ensure_ascii=False), web_search=config.llm.web_search)


def replace_meal(provider: LLMProvider, config: UserConfig, meal: PlannedMeal, inventory: list[InventoryItem], reason: str) -> PlannedMeal:
    payload = {"meal_to_replace": meal.model_dump(), "reason": reason, "servings": config.servings, "budget_eur": config.weekly_budget, "allergies": config.allergies, "dislikes": config.dislikes, "equipment": config.equipment, "inventory": _inventory_payload(inventory), "schema": PlannedMeal.model_json_schema()}
    request = LLMRequest(system=TEXT[config.language]["replace"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)
    return PlannedMeal.model_validate_json(_parse_json(provider.generate(request)))
