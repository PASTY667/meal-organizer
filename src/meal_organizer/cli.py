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
TEXT = {
    "fr": {"plan":"Plan de la semaine","day":"Jour","meal":"Repas","description":"Description","ingredients":"Ingrédients","shopping":"Liste de courses","purchase":"Prix d'achat","total":"Total des achats","pause":"Plan mis en pause. Reprends avec --resume.","saved":"Plan enregistré.","question":"Question","accept":"valider","quit":"quitter","no_inventory":"Ajoute d'abord des produits avec 'meal-organizer inventory add'.","no_plan":"Aucun plan enregistré.","recipe":"Recette","meals":"Plats de la semaine","cost_unknown":"prix indisponible","cook":"Mode cuisine","help":"valider, pause, remplacer <jour> <déjeuner|dîner>, question <jour> <déjeuner|dîner>, quitter"},
    "en": {"plan":"Weekly meal plan","day":"Day","meal":"Meal","description":"Description","ingredients":"Ingredients","shopping":"Shopping list","purchase":"Purchase price","total":"Total purchases","pause":"Plan paused. Resume with --resume.","saved":"Plan saved.","question":"Question","accept":"accept","quit":"quit","no_inventory":"Add inventory first with 'meal-organizer inventory add'.","no_plan":"No saved plan.","recipe":"Recipe","meals":"Weekly meals","cost_unknown":"price unavailable","cook":"Cooking mode","help":"accept, pause, replace <day> <lunch|dinner>, question <day> <lunch|dinner>, quit"},
}

def tr(config,key): return TEXT[config.language][key]
def ok(message): console.print(f"[bold green]✓[/bold green] {message}")
def fail(message): console.print(f"[bold red]✗[/bold red] {message}")
def warn(message): console.print(f"[bold yellow]![/bold yellow] {message}")

def choose_language(current):
    value=typer.prompt("Language / Langue [fr/en]",default=current).strip().lower()
    while value not in {"fr","en"}: value=typer.prompt("Language / Langue [fr/en]",default=current).strip().lower()
    return value

def choose_retailer(current,language):
    prompt="Supermarché de référence [leclerc/intermarche/carrefour/auchan/generic]" if language=="fr" else "Reference supermarket [leclerc/intermarche/carrefour/auchan/generic]"
    value=typer.prompt(prompt,default=current).strip().lower()
    while value not in {"leclerc","intermarche","carrefour","auchan","generic"}: value=typer.prompt(prompt,default=current).strip().lower()
    return value

def choose_llm(current,language):
    console.print(Panel.fit("[bold]Configuration LLM[/bold]" if language=="fr" else "[bold]LLM CONFIGURATION[/bold]",border_style="cyan"))
    provider=typer.prompt("Fournisseur LLM" if language=="fr" else "LLM provider",default=current.provider).strip().lower()
    while provider not in {"ollama","openrouter"}: provider=typer.prompt("Fournisseur LLM" if language=="fr" else "LLM provider",default=current.provider).strip().lower()
    if provider=="ollama":
        host=typer.prompt("URL Ollama",default=current.ollama_host); reachable,models=check_ollama(host)
        if reachable and models:
            table=Table(title="Modèles Ollama" if language=="fr" else "Ollama models"); table.add_column("Model")
            for model in models: table.add_row(model)
            console.print(table)
        model=typer.prompt("Modèle Ollama" if language=="fr" else "Ollama model",default=current.model if current.model in models else (models[0] if models else current.model)); return LLMConfig(provider="ollama",model=model,ollama_host=host,web_search=False)
    model=typer.prompt("Modèle OpenRouter" if language=="fr" else "OpenRouter model",default=current.openrouter_model or "openai/gpt-4o-mini")
    api_key=getpass("OpenRouter API key (paste supported): ") or current.openrouter_api_key
    web_search=typer.confirm("Activer la recherche web" if language=="fr" else "Enable web search",default=current.web_search)
    return LLMConfig(provider="openrouter",model=current.model,ollama_host=current.ollama_host,openrouter_model=model,openrouter_api_key=api_key,web_search=web_search)

@app.command()
def setup():
    current=load_config(); console.print(Panel.fit("[bold]MEAL ORGANIZER[/bold]",border_style="cyan")); language=choose_language(current.language)
    name=typer.prompt("Nom" if language=="fr" else "Name",default=current.name)
    budget=typer.prompt("Budget hebdomadaire (€)" if language=="fr" else "Weekly budget (€)",default=current.weekly_budget,type=float)
    servings=typer.prompt("Personnes" if language=="fr" else "Servings",default=current.servings,type=int)
    retailer=choose_retailer(current.retailer,language)
    allergies=typer.prompt("Allergies",default=", ".join(current.allergies))
    dislikes=typer.prompt("Aliments à éviter" if language=="fr" else "Foods to avoid",default=", ".join(current.dislikes))
    equipment=typer.prompt("Équipement" if language=="fr" else "Equipment",default=", ".join(current.equipment))
    llm=choose_llm(current.llm,language)
    config=UserConfig(name=name,language=language,weekly_budget=budget,servings=servings,retailer=retailer,allergies=[x.strip() for x in allergies.split(",") if x.strip()],dislikes=[x.strip() for x in dislikes.split(",") if x.strip()],equipment=[x.strip() for x in equipment.split(",") if x.strip()],llm=llm)
    save_config(config); Database(); ok(f"Configuration enregistrée → {ENV_PATH}" if language=="fr" else f"Configuration saved → {ENV_PATH}")

@app.command()
def doctor():
    config=load_config(); table=Table(title="Vérification système" if config.language=="fr" else "System check")
    table.add_column("Component"); table.add_column("Status"); table.add_column("Details")
    table.add_row("Config","[green]OK[/green]",str(ENV_PATH)); table.add_row("SQLite","[green]OK[/green]","local")
    try:
        create_provider(config.llm).generate(LLMRequest(system="Reply OK only.",prompt="OK")); table.add_row("LLM","[green]OK[/green]",config.llm.provider)
    except Exception as exc: table.add_row("LLM","[red]FAIL[/red]",str(exc)[:120])
    console.print(table)

inventory_app=typer.Typer(help="Manage inventory"); app.add_typer(inventory_app,name="inventory")
@inventory_app.command("list")
def inventory_list():
    config=load_config(); items=Database().list_inventory(); table=Table(title="Inventaire" if config.language=="fr" else "Inventory")
    for column in (["Produit","Quantité","Unité","Emplacement"] if config.language=="fr" else ["Product","Quantity","Unit","Location"]): table.add_column(column)
    for item in items: table.add_row(item.name,f"{item.quantity:g}",item.unit,item.location)
    console.print(table)
@inventory_app.command("add")
def inventory_add(name:str,quantity:float,unit:str="unit",location:str="fridge"): Database().upsert_inventory(name,quantity,unit,location); ok(f"{name} updated.")
@inventory_app.command("remove")
def inventory_remove(name:str):
    if Database().remove_inventory(name): ok(f"{name} removed.")
    else: fail(f"{name} not found."); raise typer.Exit(1)

def _meal_for(plan:MealPlan, day:str, meal:str)->PlannedMeal|None:
    aliases={"lunch":{"lunch","déjeuner","dejeuner"},"dinner":{"dinner","dîner","diner"}}
    wanted=aliases.get(meal.casefold(),{meal.casefold()})
    return next((m for m in plan.meals if m.day.casefold()==day.casefold() and m.meal.casefold() in wanted),None)

def _unpack_saved_plan(saved):
    if not saved: return None
    if len(saved)==5: return saved[0],saved[1],saved[2],saved[3],saved[4]
    if len(saved)==3: return saved[0],saved[1],saved[2],None,None
    raise ValueError(f"Unexpected saved plan shape: {len(saved)}")

def _show_week(config,plan):
    table=Table(title=tr(config,"meals"),expand=True); table.add_column(tr(config,"day")); table.add_column(tr(config,"meal")); table.add_column("Plat" if config.language=="fr" else "Dish"); table.add_column(tr(config,"description"))
    for meal in plan.meals: table.add_row(meal.day,meal.meal,meal.name,meal.description)
    console.print(table)

def _show_shopping(config,shopping,total,budget):
    table=Table(title=tr(config,"shopping")); table.add_column(tr(config,"ingredients")); table.add_column("Qté" if config.language=="fr" else "Qty",justify="right"); table.add_column(tr(config,"purchase"),justify="right")
    for item in shopping: table.add_row(item.name,f"{item.quantity:g} {item.unit}",f"{item.estimated_cost:.2f} €" if item.estimated_cost is not None else tr(config,"cost_unknown"))
    console.print(table); console.print(Panel(f"[bold]{tr(config,'total')}: {total:.2f} € / {budget:.2f} €[/bold]",border_style="green" if total<=budget else "red"))

@app.command()
def plan(resume:bool=typer.Option(False,"--resume",help="Resume the latest paused/draft plan")):
    config=load_config(); db=Database(); inventory=db.list_inventory()
    if not inventory: fail(tr(config,"no_inventory")); raise typer.Exit(1)
    provider=create_provider(config.llm); pricing=PriceService(retailer=config.retailer)
    saved=db.load_latest_plan() if resume else None
    if saved:
        plan_id,_,meal_plan,_,_=_unpack_saved_plan(saved); ok("Plan repris." if config.language=="fr" else "Plan resumed.")
    else:
        current_week=db.has_current_week_plan()
        if current_week[0]:
            plan_id,_,meal_plan,created_at,_=_unpack_saved_plan(current_week[1]); ok(f"Plan de la semaine déjà existant ({created_at[:10]})." if config.language=="fr" else f"Current week's plan already exists ({created_at[:10]}).")
        else:
            history=db.list_recent_meal_names(limit_plans=4)
            with console.status("Optimisation globale : budget prioritaire, puis variété..." if config.language=="fr" else "Global optimization: budget first, then variety..."):
                try: meal_plan=generate_plan(provider,config,inventory,history=history)
                except Exception as exc: fail(str(exc)); raise typer.Exit(1) from exc
            plan_id=db.save_plan(meal_plan,"draft")
    price_plan(meal_plan,config,inventory,enforce_budget=False,pricing=pricing); shopping=build_shopping_list(meal_plan,inventory,pricing)
    _show_week(config,meal_plan); _show_shopping(config,shopping,meal_plan.shopping_cost,config.weekly_budget)
    action=typer.prompt(f"Action ({tr(config,'help')})",default=tr(config,"accept")).strip().casefold()
    if action in {"valider","accept","ok"}:
        if meal_plan.shopping_cost > config.weekly_budget + 0.01: fail(f"Budget dépassé de {meal_plan.shopping_cost-config.weekly_budget:.2f} €."); return
        db.save_plan(meal_plan,"accepted",plan_id); ok(tr(config,"saved")); return
    if action in {"pause","p","quitter","quit","q"}: db.save_plan(meal_plan,"paused",plan_id); ok(tr(config,"pause")); return

@app.command("meals")
def meals():
    config=load_config(); saved=Database().load_latest_plan(("accepted","draft","paused")); data=_unpack_saved_plan(saved)
    if not data: fail(tr(config,"no_plan")); raise typer.Exit(1)
    _show_week(config,data[2])

@app.command()
def recipe(day:str,meal:str):
    config=load_config(); db=Database(); data=_unpack_saved_plan(db.load_latest_plan(("accepted","draft","paused")))
    if not data: fail(tr(config,"no_plan")); raise typer.Exit(1)
    plan_id,_,meal_plan,_,_=data; target=_meal_for(meal_plan,day,meal)
    if not target: fail("Repas introuvable." if config.language=="fr" else "Meal not found."); raise typer.Exit(1)
    inventory=db.list_inventory(); shopping=build_shopping_list(meal_plan,inventory,PriceService(retailer=config.retailer)); provider=create_provider(config.llm)
    with console.status("Recherche de recettes et génération..." if config.language=="fr" else "Researching recipes and generating..."):
        generated=generate_recipe(provider,config,target,inventory,shopping)
    db.save_recipe(plan_id,f"{target.day}:{target.meal}",generated)
    console.print(Panel(f"[bold]{generated.name}[/bold]\n{generated.description}\n\nPréparation: {generated.preparation_minutes} min · Cuisson: {generated.cooking_minutes} min" if config.language=="fr" else f"[bold]{generated.name}[/bold]\n{generated.description}\n\nPrep: {generated.preparation_minutes} min · Cook: {generated.cooking_minutes} min",title=tr(config,"recipe"),border_style="yellow"))

@app.command()
def cook(day:str,meal:str):
    config=load_config(); db=Database(); data=_unpack_saved_plan(db.load_latest_plan(("accepted",)))
    if not data: fail("Le plan doit être validé avant le mode cuisine."); raise typer.Exit(1)
    plan_id,_,meal_plan,_,_=data; target=_meal_for(meal_plan,day,meal)
    if not target: fail("Repas introuvable."); raise typer.Exit(1)
    key=f"{target.day}:{target.meal}"; recipe_data=db.load_recipe(plan_id,key)
    if not recipe_data:
        inventory=db.list_inventory(); shopping=build_shopping_list(meal_plan,inventory,PriceService(retailer=config.retailer)); recipe_data=generate_recipe(create_provider(config.llm),config,target,inventory,shopping); db.save_recipe(plan_id,key,recipe_data)
    console.print(Panel(f"[bold]{recipe_data.name}[/bold]",title=tr(config,"cook"),border_style="yellow"))
    for i,step in enumerate(recipe_data.steps,1):
        console.print(Panel(f"[bold]Étape {i}/{len(recipe_data.steps)}[/bold]\n{step}" if config.language=="fr" else f"[bold]Step {i}/{len(recipe_data.steps)}[/bold]\n{step}",border_style="cyan"))
        if i<len(recipe_data.steps) and typer.prompt("Entrée pour continuer, q pour quitter",default="",show_default=False).casefold()=="q": return

@app.command()
def price(product:str):
    config=load_config(); estimate=PriceService(retailer=config.retailer).estimate(product)
    console.print(Panel(f"{estimate.product}\n{estimate.price:.2f} €\n{estimate.package_quantity:g} {estimate.package_unit}\nSource: {estimate.source}\nConfiance: {estimate.confidence}",title=f"Prix — {product}"))

if __name__=="__main__": app()
