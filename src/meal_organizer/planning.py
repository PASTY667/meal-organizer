import json

from .config import UserConfig
from .db import InventoryItem
from .llm import LLMProvider, LLMRequest
from .models import MealPlan

SYSTEM_PROMPT = """You are the planning engine for Meal Organizer.
Allergies are hard constraints: never include an allergen supplied by the user.
Foods explicitly marked as disliked must not appear.
Only use cooking equipment supplied by the user.
Prefer ingredients already in inventory and minimize food waste.
Stay within the weekly budget.
Return JSON only, matching the requested schema. Costs are estimates, never guaranteed prices.
"""


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
            "allergies": config.allergies,
            "dislikes": config.dislikes,
            "equipment": config.equipment,
            "inventory": inventory_text,
            "required_output_schema": schema,
        },
        ensure_ascii=False,
        indent=2,
    )
    return LLMRequest(system=SYSTEM_PROMPT, prompt=prompt, json_mode=True)


def generate_plan(provider: LLMProvider, config: UserConfig, inventory: list[InventoryItem]) -> MealPlan:
    response = provider.generate(build_plan_request(config, inventory))
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    plan = MealPlan.model_validate_json(cleaned)
    if plan.total_estimated_cost > config.weekly_budget + 0.01:
        raise ValueError(
            f"Generated plan exceeds budget: {plan.total_estimated_cost:.2f} > {config.weekly_budget:.2f} EUR"
        )
    return plan
