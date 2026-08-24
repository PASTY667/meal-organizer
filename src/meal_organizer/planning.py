import json
import re

from .config import UserConfig
from .db import InventoryItem
from .llm import LLMProvider, LLMRequest
from .models import MealIngredient, MealPlan, PlannedMeal, Recipe
from .pricing import PriceService, canonical_product

TEXT = {
    "fr": {"system": """Tu es le moteur de planification de Meal Organizer. Réponds en français.
Construis d'abord mentalement une semaine complète et cohérente avant de produire le JSON. Le budget concerne les achats réellement nécessaires, pas les aliments déjà possédés.
Utilise le stock fourni en priorité et ne prévois jamais l'achat d'un ingrédient si le stock couvre le besoin hebdomadaire après normalisation du nom.
Planifie exactement 14 repas : déjeuner et dîner pour chacun des 7 jours, avec des portions normales et rassasiantes.
Réutilise intelligemment les ingrédients achetés, limite le gaspillage et garde une alimentation variée et équilibrée.
Allergies = contraintes absolues. Les aliments refusés ne doivent jamais apparaître. N'utilise que l'équipement fourni.
Ne rédige pas les recettes complètes et ne donne aucun prix. Donne uniquement nom, description et ingrédients avec quantités.
Si la recherche web est disponible, utilise-la pour trouver des idées crédibles puis adapte-les.
Retourne uniquement le JSON correspondant au schéma fourni.""", "recipe": "Génère une recette détaillée en français à partir du repas choisi, du stock et de la liste de courses. Respecte strictement allergies, aliments refusés, équipement et nombre de portions. Recherche sur le web si disponible et adapte une recette crédible.", "question": "Réponds en français à la question de l'utilisateur sur ce repas sans modifier le plan.", "replace": "Remplace uniquement le repas demandé en tenant compte de toute la semaine, du budget, du stock et des achats déjà prévus. Retourne uniquement un PlannedMeal JSON."},
    "en": {"system": """You are the Meal Organizer planning engine. Respond in English.
First reason about a complete, coherent week before producing JSON. The budget concerns purchases actually needed, not food already owned.
Prioritize inventory and never plan a purchase for an ingredient when normalized inventory already covers the week's requirement.
Plan exactly 14 meals: lunch and dinner for each of 7 days, with normal satisfying portions.
Reuse purchased ingredients intelligently, minimize waste and keep meals varied and balanced.
Allergies are hard constraints. Disliked foods must never appear. Only use the provided equipment.
Do not write full recipes or prices. Give only name, description and ingredient quantities.
Use web research when available to find credible ideas and adapt them.
Return only JSON matching the supplied schema.""", "recipe": "Generate a detailed recipe in English from the selected meal, inventory and shopping list. Strictly respect allergies, dislikes, equipment and servings. Search the web when available and adapt a credible recipe.", "question": "Answer the user's question about this meal in English without changing the plan.", "replace": "Replace only the requested meal while considering the whole week, budget, inventory and planned purchases. Return only a PlannedMeal JSON object."},
}

def _inventory_payload(inventory):
    return [{"name": i.name, "quantity": i.quantity, "unit": i.unit, "location": i.location} for i in inventory]

def _parse_json(response: str):
    cleaned = response.strip()
    if cleaned.startswith("```"): cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return cleaned

def _coerce_plan_payload(response: str) -> dict:
    payload = json.loads(_parse_json(response))
    if isinstance(payload, dict) and isinstance(payload.get("meals"), list):
        meals = []
        for item in payload["meals"]:
            if isinstance(item, dict) and isinstance(item.get("meals"), list): meals.extend(item["meals"])
            elif isinstance(item, list): meals.extend(item)
            else: meals.append(item)
        payload["meals"] = meals
        return payload
    if isinstance(payload, list):
        meals = []
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("meals"), list): meals.extend(item["meals"])
            elif isinstance(item, list): meals.extend(item)
            else: meals.append(item)
        return {"meals": meals}
    raise ValueError("LLM returned an invalid meal plan JSON shape")

def build_plan_request(config, inventory):
    payload = {"servings": config.servings, "weekly_budget_eur": config.weekly_budget, "language": config.language, "allergies": config.allergies, "dislikes": config.dislikes, "equipment": config.equipment, "inventory": _inventory_payload(inventory), "planning_goal": "Design the complete week first and optimize the shopping basket globally.", "schema": MealPlan.model_json_schema()}
    return LLMRequest(system=TEXT[config.language]["system"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)

def _normalise(value, unit):
    unit = unit.lower().strip()
    if unit == "kg": return value * 1000, "g"
    if unit in {"g", "gram", "grams", "gramme", "grammes"}: return value, "g"
    if unit == "l": return value * 1000, "ml"
    if unit in {"ml", "millilitre", "millilitres", "milliliter", "milliliters"}: return value, "ml"
    if unit in {"unit", "units", "piece", "pieces", "pcs", "pièce", "pièces"}: return value, "unit"
    return value, "unit"

def _inventory_quantity(name, unit, inventory):
    target = _normalise(0, unit)[1]; wanted = canonical_product(name); total = 0.0
    for item in inventory:
        if canonical_product(item.name) != wanted: continue
        value, item_unit = _normalise(item.quantity, item.unit)
        if item_unit == target: total += value
    return total

def build_shopping_list(plan, inventory, pricing=None):
    grouped = {}
    for meal in plan.meals:
        for ingredient in meal.ingredients:
            quantity, unit = _normalise(ingredient.quantity, ingredient.unit)
            key = (canonical_product(ingredient.name), unit)
            if key not in grouped: grouped[key] = {"name": ingredient.name, "quantity": 0.0, "unit": unit}
            grouped[key]["quantity"] += quantity
    result = []; pricing = pricing or PriceService()
    for item in grouped.values():
        name, unit, required = item["name"], item["unit"], item["quantity"]
        missing = max(0.0, required - _inventory_quantity(name, unit, inventory))
        if missing <= 0: continue
        result.append(MealIngredient(name=name, quantity=round(missing, 2), unit=unit, estimated_cost=pricing.purchase_cost(name, missing, unit)))
    return result

def price_plan(plan, config, inventory, enforce_budget=True, pricing=None):
    pricing = pricing or PriceService()
    for meal in plan.meals:
        meal_cost = 0.0
        for ingredient in meal.ingredients:
            ingredient.estimated_cost = pricing.cost(ingredient.name, ingredient.quantity, ingredient.unit)
            if ingredient.estimated_cost is not None: meal_cost += ingredient.estimated_cost
        meal.estimated_cost = round(meal_cost, 2) if meal_cost else None
    shopping = build_shopping_list(plan, inventory, pricing)
    plan.shopping_cost = round(sum(item.estimated_cost or 0 for item in shopping), 2)
    plan.total_food_cost = round(sum(meal.estimated_cost or 0 for meal in plan.meals), 2)
    if enforce_budget and plan.shopping_cost > config.weekly_budget + 0.01: raise ValueError(f"Plan exceeds weekly shopping budget: {plan.shopping_cost:.2f} > {config.weekly_budget:.2f} EUR")
    return plan

def generate_plan(provider, config, inventory):
    raw = provider.generate(build_plan_request(config, inventory))
    plan = MealPlan.model_validate(_coerce_plan_payload(raw))
    if len(plan.meals) != 14: raise ValueError(f"Expected 14 meals, received {len(plan.meals)}")
    return price_plan(plan, config, inventory, enforce_budget=False)

def build_recipe_request(config, meal, inventory, shopping):
    payload = {"servings": config.servings, "meal": meal.model_dump(), "inventory": _inventory_payload(inventory), "shopping_list": [i.model_dump() for i in shopping], "schema": Recipe.model_json_schema()}
    return LLMRequest(system=TEXT[config.language]["recipe"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)

def generate_recipe(provider, config, meal, inventory, shopping):
    return Recipe.model_validate_json(_parse_json(provider.generate(build_recipe_request(config, meal, inventory, shopping))))

def build_question_request(config, meal, question):
    return LLMRequest(system=TEXT[config.language]["question"], prompt=json.dumps({"meal": meal.model_dump(), "question": question}, ensure_ascii=False), web_search=config.llm.web_search)

def replace_meal(provider, config, meal, inventory, reason):
    payload = {"meal_to_replace": meal.model_dump(), "reason": reason, "servings": config.servings, "budget_eur": config.weekly_budget, "allergies": config.allergies, "dislikes": config.dislikes, "equipment": config.equipment, "inventory": _inventory_payload(inventory), "schema": PlannedMeal.model_json_schema()}
    request = LLMRequest(system=TEXT[config.language]["replace"], prompt=json.dumps(payload, ensure_ascii=False, indent=2), json_mode=True, web_search=config.llm.web_search)
    return PlannedMeal.model_validate_json(_parse_json(provider.generate(request)))
