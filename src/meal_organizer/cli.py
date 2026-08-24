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

app = typer.Typer(help="Meal Organizer", no_args_is_help=True)
console = Console()
TEXT = {"fr":{"no_plan":"Aucun plan enregistré.","recipe":"Recette"},"en":{"no_plan":"No saved plan.","recipe":"Recipe"}}

def tr(config,key): return TEXT[config.language][key]
def fail(message): console.print(f"[bold red]✗[/bold red] {message}
")

def _unpack_saved_plan(saved):
    if not saved: return None
    if len(saved)==5: return saved[0],saved[1],saved[2],saved[3],saved[4]
    if len(saved)==3: return saved[0],saved[1],saved[2],None,None
    raise ValueError(f"Unexpected saved plan shape: {len(saved)}")

def _meal_for(plan:MealPlan, day:str, meal:str)->PlannedMeal|None:
    aliases={"lunch":{"lunch","déjeuner","dejeuner"},"dinner":{"dinner","dîner","diner"}}
    wanted=aliases.get(meal.casefold(),{meal.casefold()})
    return next((m for m in plan.meals if m.day.casefold()==day.casefold() and m.meal.casefold() in wanted),None)

@app.command()
def recipe(day:str,meal:str):
    config=load_config(); db=Database(); saved=db.load_latest_plan(("accepted","draft","paused"))
    if not saved: fail(tr(config,"no_plan")); raise typer.Exit(1)
    plan_id,_,meal_plan,_,_=_unpack_saved_plan(saved); target=_meal_for(meal_plan,day,meal)
    if not target: fail("Repas introuvable." if config.language=="fr" else "Meal not found."); raise typer.Exit(1)
    inventory=db.list_inventory(); shopping=build_shopping_list(meal_plan,inventory,PriceService(retailer=config.retailer)); provider=create_provider(config.llm)
    with console.status("Recherche de recettes et génération..." if config.language=="fr" else "Researching recipes and generating..."):
        generated=generate_recipe(provider,config,target,inventory,shopping)
    key=f"{target.day}:{target.meal}"; db.save_recipe(plan_id,key,generated)
    console.print(Panel(f"[bold]{generated.name}[/bold]\n{generated.description}\n\nPréparation: {generated.preparation_minutes} min · Cuisson: {generated.cooking_minutes} min" if config.language=="fr" else f"[bold]{generated.name}[/bold]\n{generated.description}\n\nPrep: {generated.preparation_minutes} min · Cook: {generated.cooking_minutes} min",title=tr(config,"recipe"),border_style="yellow"))
    console.print("Utilise 'meal-organizer cook <jour> <déjeuner|dîner>' pour cuisiner étape par étape." if config.language=="fr" else "Use 'meal-organizer cook <day> <lunch|dinner>' to cook step by step.")

if __name__=="__main__": app()
