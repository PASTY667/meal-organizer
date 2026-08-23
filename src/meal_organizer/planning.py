import json

from .config import UserConfig
from .db import InventoryItem
from .llm import LLMProvider, LLMRequest
from .models import MealIngredient, MealPlan, PlannedMeal, Recipe
from .pricing import PriceService


TEXT = {
    "fr": {
        "system": """Tu es le moteur de planification de Meal Organizer. Réponds en français.
Les allergies sont des contraintes absolues : ne propose jamais un allergène fourni par l'utilisateur.
Les aliments explicitement refusés ne doivent jamais apparaître.
N'utilise que l'équipement fourni.
Utilise le stock existant lorsqu'il est pertinent, mais construis aussi une liste de courses réaliste pour compléter la semaine.
Le budget est une contrainte forte. Préfère les ingrédients polyvalents et limite le gaspillage.
Planifie exactement deux repas par jour : déjeuner et dîner, soit 14 repas.
Ne rédige pas les recettes complètes : donne seulement le nom, une description courte et les ingrédients/quantités nécessaires.
Les coûts doivent rester à zéro dans ta réponse : l'application les calcule à partir de sources de prix externes.
Retourne uniquement le JSON correspondant au schéma fourni.""",
        "recipe": "Génère une recette détaillée en français à partir du repas planifié, du stock et de la liste de courses. Respecte strictement allergies, aliments refusés et équipement. Donne des étapes numérotées simples, adaptées à un étudiant. Si une recherche web est disponible, privilégie des recettes réelles et crédibles et indique les sources utilisées.",
        "question": "Réponds en français à la question de l'utilisateur sur ce repas. Ne modifie pas le plan tant que l'utilisateur ne le demande pas explicitement.",
        "recipe_question": "Réponds en français à la question de l'utilisateur sur cette recette. Sois pratique et précis, en respectant les ingrédients, l'équipement et les contraintes alimentaires du plan.",
        "replace": "Remplace uniquement le repas demandé. Respecte strictement les contraintes, le budget et le stock. Retourne uniquement un objet PlannedMeal JSON correspondant au schéma fourni.",
    },
    "en": {
        "system": """You are the Meal Organizer planning engine. Respond in English.
Allergies are hard constraints: never include a user-provided allergen.
Explicitly disliked foods must never appear.
Only use the equipment provided.
Use existing inventory when useful, but also build a realistic shopping list to complete the week.
Budget is a hard constraint. Prefer versatile ingredients and minimize waste.
Plan exactly two meals per day: lunch and dinner, 14 meals total.
Do not write full recipes: only provide the meal name, a short description, and required ingredients/quantities.
Keep costs at zero in your response: the application calculates them from external price data.
Return JSON only matching the supplied schema.""",
        "recipe": "Generate a detailed recipe in English from the planned meal, inventory and shopping list. Strictly respect allergies, disliked foods and equipment. Give simple numbered steps suitable for a student. If web research is available, prefer real, credible recipes and include the sources used.",
        "question": "Answer the user's question about this meal in English. Do not change the plan unless the user explicitly asks you to.",
        "recipe_question": "Answer the user's question about this recipe in English. Be practical and precise while respecting the ingredients, equipment and dietary constraints of the plan.",
        "replace": "Replace only the requested meal. Strictly respect constraints, budget and inventory. Return only a PlannedMeal JSON object matching the supplied schema.",
    },
}


def _inventory_payload(inventory: list[InventoryItem]) -> list[dict]:
    return [{"name": item.name, "quantity": item.quantity, "unit": item.unit, "location": item.location} for item in inventory]


def build_plan_request(config: UserConfig, inventory: list[InventoryItem]) -> LLMRequest:
    payload = {"servings": config.servings, "weekly_budget_eur": config.weekly_budget, "language": config.language, "allergies": config.allergies, "dislikes": config.dislikes, "equipment": config.equipment, "inventory": _inventory_payload(inventory), "required_output_schema": MealPlan.model_json_schema()}
    return LLMRequest(system=TEXT[config.language]["system"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True)


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


def price_plan(plan: MealPlan, config: UserConfig, inventory: list[InventoryItem]) -> MealPlan:
    pricing = PriceService()
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
    if plan.shopping_cost > config.weekly_budget + 0.01:
        raise ValueError(f"Plan exceeds weekly shopping budget: {plan.shopping_cost:.2f} > {config.weekly_budget:.2f} EUR")
    return plan


def _parse_json(response: str):
    cleaned = response.strip()
    if cleaned.startswith("```"): cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return cleaned


def generate_plan(provider: LLMProvider, config: UserConfig, inventory: list[InventoryItem]) -> MealPlan:
    plan = MealPlan.model_validate_json(_parse_json(provider.generate(build_plan_request(config, inventory))))
    if len(plan.meals) != 14: raise ValueError(f"Expected 14 meals, received {len(plan.meals)}")
    return price_plan(plan, config, inventory)


def build_shopping_list(plan: MealPlan, inventory: list[InventoryItem], pricing: PriceService | None = None) -> list[MealIngredient]:
    grouped: dict[tuple[str, str], MealIngredient] = {}
    for meal in plan.meals:
        for ingredient in meal.ingredients:
            _, unit = _normalise(0, ingredient.unit); key = (ingredient.name.casefold(), unit)
            if key not in grouped: grouped[key] = MealIngredient(name=ingredient.name, quantity=0, unit=unit)
            grouped[key].quantity += _normalise(ingredient.quantity, ingredient.unit)[0]
    result: list[MealIngredient] = []; pricing = pricing or PriceService()
    for item in grouped.values():
        missing = max(0, item.quantity - _inventory_quantity(item.name, item.unit, inventory))
        if missing > 0:
            item.quantity = round(missing, 2)
            estimate = pricing.estimate(item.name)
            item.estimated_cost = estimate.purchase_cost(missing, item.unit) if estimate else None
            result.append(item)
    return result


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
