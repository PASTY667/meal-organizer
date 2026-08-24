from getpass import getpass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import ENV_PATH, LLMConfig, UserConfig, check_ollama, load_config, save_config
from .db import Database
from .llm import LLMRequest, create_provider
from .models import MealPlan, PlannedMeal
from .planning import build_question_request, build_shopping_list, generate_plan, generate_recipe, price_plan, replace_meal
from .pricing import PriceService

# Existing CLI code remains unchanged above/below this compatibility helper.

def _unpack_saved_plan(saved):
    if not saved:
        return None
    if len(saved) == 5:
        plan_id, status, meal_plan, created_at, updated_at = saved
    elif len(saved) == 3:
        plan_id, status, meal_plan = saved
        created_at = updated_at = None
    else:
        raise ValueError(f"Unexpected saved plan shape: {len(saved)} values")
    return plan_id, status, meal_plan, created_at, updated_at

def recipe(day: str, meal: str):
    config = load_config()
    db = Database()
    saved = db.load_latest_plan(("accepted", "draft", "paused"))
    if not saved:
        fail(tr(config, "no_plan"))
        raise typer.Exit(1)
    plan_id, _, meal_plan, _, _ = _unpack_saved_plan(saved)
    target = _meal_for(meal_plan, day, meal)
    if not target:
        fail("Repas introuvable." if config.language == "fr" else "Meal not found.")
        raise typer.Exit(1)
    inventory = db.list_inventory()
    shopping = build_shopping_list(meal_plan, inventory, PriceService(retailer=config.retailer))
    provider = create_provider(config.llm)
    with console.status("Recherche de recettes et génération..." if config.language == "fr" else "Researching recipes and generating..."):
        generated = generate_recipe(provider, config, target, inventory, shopping)
    key = f"{target.day}:{target.meal}"
    db.save_recipe(plan_id, key, generated)
    console.print(Panel(f"[bold]{generated.name}[/bold]\n{generated.description}\n\nPréparation: {generated.preparation_minutes} min · Cuisson: {generated.cooking_minutes} min" if config.language == "fr" else f"[bold]{generated.name}[/bold]\n{generated.description}\n\nPrep: {generated.preparation_minutes} min · Cook: {generated.cooking_minutes} min", title=tr(config, "recipe"), border_style="yellow"))
    console.print("Utilise 'meal-organizer cook <jour> <déjeuner|dîner>' pour cuisiner étape par étape." if config.language == "fr" else "Use 'meal-organizer cook <day> <lunch|dinner>' to cook step by step.")
