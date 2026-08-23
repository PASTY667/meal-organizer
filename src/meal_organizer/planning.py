import json
from collections import defaultdict

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
        "recipe": "Génère une recette détaillée en français à partir du repas planifié, du stock et de la liste de courses. Respecte strictement allergies, aliments refusés et équipement. Donne des étapes numérotées simples, adaptées à un étudiant.",
        "question": "Réponds en français à la question de l'utilisateur sur ce repas. Ne modifie pas le plan tant que l'utilisateur ne le demande pas explicitement.",
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
        "recipe": "Generate a detailed recipe in English from the planned meal, inventory and shopping list. Strictly respect allergies, disliked foods and equipment. Give simple numbered steps suitable for a student.",
        "question": "Answer the user's question about this meal in English. Do not change the plan unless the user explicitly asks you to.",
    },
}


def build_plan_request(config: UserConfig, inventory: list[InventoryItem]) -> LLMRequest:
    inventory_text = [
        {"name": item.name, "quantity": item.quantity, "unit": item.unit, "location": item.location}
        for item in inventory
    ]
    schema = MealPlan.model_json_schema()
    prompt = json.dumps(
        {
            "servings": config.servings,
            "weekly_budget_eur": config.weekly_budget,
            "language": config.language,
            "allergies": config.allergies,
            "dislikes": config.dislikes,
            "equipment": config.equipment,
            "inventory": inventory_text,
            "required_output_schema": schema,
        },
        ensure_ascii=False,
        indent=2,
    )
    return LLMRequest(system=TEXT[config.language]["system"], prompt=prompt, json_mode=True)


def _normalise(value: float, unit: str) -> tuple[float, str]:
    unit = unit.lower().strip()
    if unit == "kg":
        return value * 1000, "g"
    if unit in {"g", "gram", "grams"}:
        return value, "g"
    if unit == "l":
        return value * 1000, "ml"
    if unit in {"ml", "millilitre", "millilitres"}:
        return value, "ml"
    return value, "unit"


def _inventory_quantity(name: str, unit: str, inventory: list[InventoryItem]) -> float:
    target = _normalise(0, unit)[1]
    total = 0.0
    for item in inventory:
        if item.name.casefold() != name.casefold():
            continue
        item_value, item_unit = _normalise(item.quantity, item.unit)
        if item_unit == target:
            total += item_value
        elif target == "unit" and item_unit == "unit":
            total += item_value
    return total


def price_plan(plan: MealPlan, config: UserConfig, inventory: list[InventoryItem]) -> MealPlan:
    pricing = PriceService()
    shopping_cost = 0.0
    total_food_cost = 0.0
    for meal in plan.meals:
        meal_cost = 0.0
        for ingredient in meal.ingredients:
            available = _inventory_quantity(ingredient.name, ingredient.unit, inventory)
            required_value, required_unit = _normalise(ingredient.quantity, ingredient.unit)
            available = _inventory_quantity(ingredient.name, required_unit, inventory)
            missing = max(0.0, required_value - available)
            if missing > 0:
                missing_unit = required_unit
                estimate = pricing.estimate(ingredient.name)
                ingredient.estimated_cost = estimate.cost_for(missing, missing_unit) if estimate else None
                if ingredient.estimated_cost is not None:
                    shopping_cost += ingredient.estimated_cost
            else:
                ingredient.estimated_cost = pricing.cost(ingredient.name, required_value, required_unit)
            if ingredient.estimated_cost is not None:
                meal_cost += ingredient.estimated_cost
        meal.estimated_cost = round(meal_cost, 2) if meal_cost else None
        total_food_cost += meal_cost
    plan.shopping_cost = round(shopping_cost, 2)
    plan.total_food_cost = round(total_food_cost, 2)
    if plan.shopping_cost > config.weekly_budget + 0.01:
        raise ValueError(
            f"Plan exceeds weekly shopping budget: {plan.shopping_cost:.2f} > {config.weekly_budget:.2f} EUR"
        )
    return plan


def generate_plan(provider: LLMProvider, config: UserConfig, inventory: list[InventoryItem]) -> MealPlan:
    response = provider.generate(build_plan_request(config, inventory))
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    plan = MealPlan.model_validate_json(cleaned)
    if len(plan.meals) != 14:
        raise ValueError(f"Expected 14 meals, received {len(plan.meals)}")
    return price_plan(plan, config, inventory)


def build_shopping_list(plan: MealPlan, inventory: list[InventoryItem]) -> list[MealIngredient]:
    grouped: dict[tuple[str, str], MealIngredient] = {}
    for meal in plan.meals:
        for ingredient in meal.ingredients:
            key = (ingredient.name.casefold(), _normalise(0, ingredient.unit)[1])
            if key not in grouped:
                grouped[key] = MealIngredient(name=ingredient.name, quantity=0, unit=key[1])
            grouped[key].quantity += _normalise(ingredient.quantity, ingredient.unit)[0]
    result: list[MealIngredient] = []
    for item in grouped.values():
        available = _inventory_quantity(item.name, item.unit, inventory)
        missing = max(0, item.quantity - available)
        if missing > 0:
            item.quantity = round(missing, 2)
            result.append(item)
    return result


def build_recipe_request(config: UserConfig, meal: PlannedMeal, inventory: list[InventoryItem], shopping: list[MealIngredient], question: str | None = None) -> LLMRequest:
    payload = {
        "servings": config.servings,
        "meal": meal.model_dump(),
        "inventory": [item.__dict__ if hasattr(item, "__dict__") else {"name": item.name, "quantity": item.quantity, "unit": item.unit, "location": item.location} for item in inventory],
        "shopping_list": [item.model_dump() for item in shopping],
        "question": question,
        "schema": Recipe.model_json_schema(),
    }
    return LLMRequest(
        system=TEXT[config.language]["recipe"],
        prompt=json.dumps(payload, ensure_ascii=False, indent=2),
        json_mode=True,
        web_search=config.llm.web_search,
    )
