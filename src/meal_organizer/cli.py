from getpass import getpass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import ENV_PATH, LLMConfig, UserConfig, check_ollama, load_config, save_config
from .db import Database
from .llm import LLMRequest, create_provider
from .models import MealPlan, PlannedMeal
from .planning import build_question_request, build_shopping_list, generate_day_options, generate_recipe, price_plan, replace_meal
from .pricing import PriceService

app = typer.Typer(help="Meal Organizer", no_args_is_help=True)
console = Console()
TEXT = {"fr": {"plan":"Plan de la semaine","day":"Jour","meal":"Repas","description":"Description","ingredients":"Ingrédients","cost":"Coût du repas","shopping":"Liste de courses","purchase":"Prix d'achat","total":"Achats estimés","budget":"Budget","pause":"Plan mis en pause. Reprends avec --resume.","saved":"Plan enregistré.","question":"Question","replace":"Remplacer","choose":"Choisis une option","regenerate":"régénérer","quit":"quitter","accept":"valider","no_inventory":"Ajoute d'abord des produits avec 'meal-organizer inventory add'.","no_plan":"Aucun plan enregistré.","recipe":"Recette","steps":"Étapes"},"en": {"plan":"Weekly meal plan","day":"Day","meal":"Meal","description":"Description","ingredients":"Ingredients","cost":"Meal cost","shopping":"Shopping list","purchase":"Purchase price","total":"Estimated purchases","budget":"Budget","pause":"Plan paused. Resume with --resume.","saved":"Plan saved.","question":"Question","replace":"Replace","choose":"Choose an option","regenerate":"regenerate","quit":"quit","accept":"accept","no_inventory":"Add inventory first with 'meal-organizer inventory add'.","no_plan":"No saved plan.","recipe":"Recipe","steps":"Steps"}}
DAYS = {"fr":["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"],"en":["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]}

def tr(config,key): return TEXT[config.language][key]
def ok(message): console.print(f"[bold green]✓[/bold green] {message}")
def fail(message): console.print(f"[bold red]✗[/bold red] {message}")
def warn(message): console.print(f"[bold yellow]![/bold yellow] {message}")

def choose_language(current):
    value=typer.prompt("Language / Langue [fr/en]",default=current).strip().lower()
    while value not in {"fr","en"}: value=typer.prompt("Language / Langue [fr/en]",default=current).strip().lower()
    return value

def choose_llm(current,language):
    console.print(Panel.fit("[bold]Configuration LLM[/bold]" if language=="fr" else "[bold]LLM CONFIGURATION[/bold]",border_style="cyan"))
    provider=typer.prompt("Fournisseur LLM" if language=="fr" else "LLM provider",default=current.provider).strip().lower()
    while provider not in {"ollama","openrouter"}: provider=typer.prompt("Fournisseur LLM" if language=="fr" else "LLM provider",default=current.provider).strip().lower()
    if provider=="ollama":
        host=typer.prompt("URL Ollama",default=current.ollama_host); reachable,models=check_ollama(host)
        if reachable and models:
            table=Table(title="Modèles Ollama"); table.add_column("Model")
            for model in models: table.add_row(model)
            console.print(table)
        model=typer.prompt("Modèle Ollama",default=current.model if current.model in models else (models[0] if models else current.model))
        return LLMConfig(provider="ollama",model=model,ollama_host=host,web_search=False)
    model=typer.prompt("Modèle OpenRouter",default=current.openrouter_model or "openai/gpt-4o-mini"); api_key=getpass("OpenRouter API key (paste supported): ") or current.openrouter_api_key; web_search=typer.confirm("Activer la recherche web pour les recettes" if language=="fr" else "Enable web search for recipes",default=current.web_search)
    return LLMConfig(provider="openrouter",model=current.model,ollama_host=current.ollama_host,openrouter_model=model,openrouter_api_key=api_key,web_search=web_search)

@app.command()
def setup():
    current=load_config(); console.print(Panel.fit("[bold]MEAL ORGANIZER[/bold]",border_style="cyan")); language=choose_language(current.language)
    name=typer.prompt("Nom" if language=="fr" else "Name",default=current.name); budget=typer.prompt("Budget hebdomadaire (€)" if language=="fr" else "Weekly budget (€)",default=current.weekly_budget,type=float); servings=typer.prompt("Personnes" if language=="fr" else "Servings",default=current.servings,type=int)
    allergies=typer.prompt("Allergies",default=", ".join(current.allergies)); dislikes=typer.prompt("Aliments à éviter" if language=="fr" else "Foods to avoid",default=", ".join(current.dislikes)); equipment=typer.prompt("Équipement" if language=="fr" else "Equipment",default=", ".join(current.equipment)); llm=choose_llm(current.llm,language)
    config=UserConfig(name=name,language=language,weekly_budget=budget,servings=servings,allergies=[x.strip() for x in allergies.split(",") if x.strip()],dislikes=[x.strip() for x in dislikes.split(",") if x.strip()],equipment=[x.strip() for x in equipment.split(",") if x.strip()],llm=llm); save_config(config); Database(); ok(f"Configuration enregistrée → {ENV_PATH}" if language=="fr" else f"Configuration saved → {ENV_PATH}")

@app.command()
def doctor():
    config=load_config(); table=Table(title="System check"); table.add_column("Component"); table.add_column("Status"); table.add_column("Details"); table.add_row("Config","[green]OK[/green]",str(ENV_PATH)); table.add_row("SQLite","[green]OK[/green]","local")
    try: create_provider(config.llm).generate(LLMRequest(system="Reply OK only.",prompt="OK")); table.add_row("LLM","[green]OK[/green]",config.llm.provider)
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

def show_summary(config,plan,shopping):
    table=Table(title=tr(config,"plan"),expand=True)
    for c in [tr(config,"day"),tr(config,"meal"),tr(config,"description"),tr(config,"ingredients"),tr(config,"cost")]: table.add_column(c)
    for meal in plan.meals:
        ingredients=", ".join(f"{i.quantity:g} {i.unit} {i.name}" for i in meal.ingredients); cost=f"{meal.estimated_cost:.2f} €" if meal.estimated_cost is not None else "—"; table.add_row(meal.day,meal.meal,f"[bold]{meal.name}[/bold]\n{meal.description}",ingredients,cost)
    console.print(table); shop=Table(title=tr(config,"shopping")); shop.add_column(tr(config,"ingredients")); shop.add_column("Qté" if config.language=="fr" else "Qty"); shop.add_column(tr(config,"purchase"))
    for item in shopping: shop.add_row(item.name,f"{item.quantity:g} {item.unit}",f"{item.estimated_cost:.2f} €" if item.estimated_cost is not None else "indisponible")
    console.print(shop); console.print(Panel(f"[bold]{tr(config,'total')}: {plan.shopping_cost:.2f} € / {config.weekly_budget:.2f} €[/bold]",border_style="green"))

def choose_meal(config,provider,options,meal_type):
    allowed={"déjeuner","dejeuner","lunch"} if meal_type=="lunch" else {"dîner","diner","dinner"}; candidates=[m for m in options if m.meal.casefold() in allowed]
    table=Table(title="Déjeuner" if meal_type=="lunch" and config.language=="fr" else "Lunch" if meal_type=="lunch" else "Dîner" if config.language=="fr" else "Dinner"); table.add_column("#"); table.add_column("Plat"); table.add_column("Description"); table.add_column("Coût")
    for i,m in enumerate(candidates,1): table.add_row(str(i),m.name,m.description,f"{m.estimated_cost:.2f} €" if m.estimated_cost is not None else "—")
    console.print(table)
    while True:
        value=typer.prompt(f"{tr(config,'choose')} (1/2, q, r, p)").strip().lower()
        if value=="p": return None
        if value=="r": return "REGENERATE"
        if value=="q":
            idx=typer.prompt("Option",type=int); question=typer.prompt(tr(config,"question")); console.print(Panel(provider.generate(build_question_request(config,candidates[idx-1],question)),title=tr(config,"question"),border_style="cyan")); continue
        if value in {"1","2"}: return candidates[int(value)-1]
        warn("Choisis 1, 2, q, r ou p." if config.language=="fr" else "Choose 1, 2, q, r or p.")

@app.command()
def plan(resume:bool=typer.Option(False,"--resume",help="Resume the latest paused/draft plan")):
    config=load_config(); db=Database(); inventory=db.list_inventory()
    if not inventory: fail(tr(config,"no_inventory")); raise typer.Exit(1)
    provider=create_provider(config.llm); pricing=PriceService(); saved=db.load_latest_plan() if resume else None
    if saved: plan_id,_,meal_plan=saved; ok("Plan repris." if config.language=="fr" else "Plan resumed.")
    else: meal_plan=MealPlan(meals=[]); plan_id=db.save_plan(meal_plan,"draft")
    for day_index,day in enumerate(DAYS[config.language]):
        if len(meal_plan.meals)>=day_index*2+2: continue
        while True:
            with console.status(f"Recherche de plats pour {day}..." if config.language=="fr" else f"Finding dishes for {day}..."):
                options=generate_day_options(provider,config,inventory,meal_plan.meals,day)
                for option in options: price_plan(MealPlan(meals=[option]),config,inventory,enforce_budget=False,pricing=pricing)
            lunch=choose_meal(config,provider,options,"lunch")
            if lunch is None: db.save_plan(meal_plan,"paused",plan_id); ok(tr(config,"pause")); return
            if lunch=="REGENERATE": continue
            dinner=choose_meal(config,provider,options,"dinner")
            if dinner is None: db.save_plan(meal_plan,"paused",plan_id); ok(tr(config,"pause")); return
            if dinner=="REGENERATE": continue
            meal_plan.meals.extend([lunch,dinner]); price_plan(meal_plan,config,inventory,enforce_budget=False,pricing=pricing); db.save_plan(meal_plan,"draft",plan_id); console.print(Panel(f"{day} — {lunch.name} / {dinner.name}\n{tr(config,'total')}: {meal_plan.shopping_cost:.2f} € / {config.weekly_budget:.2f} €",border_style="green")); break
    price_plan(meal_plan,config,inventory,enforce_budget=False,pricing=pricing); show_summary(config,meal_plan,build_shopping_list(meal_plan,inventory,pricing))
    if meal_plan.shopping_cost>config.weekly_budget: warn(f"Budget dépassé : {meal_plan.shopping_cost:.2f} € > {config.weekly_budget:.2f} €" if config.language=="fr" else f"Budget exceeded: {meal_plan.shopping_cost:.2f} € > {config.weekly_budget:.2f} €")
    action=typer.prompt(f"{tr(config,'accept')} / {tr(config,'pause')} / {tr(config,'quit')}",default=tr(config,'accept')).strip().lower()
    if action.startswith("p"): db.save_plan(meal_plan,"paused",plan_id); ok(tr(config,"pause")); return
    db.save_plan(meal_plan,"accepted",plan_id); ok(tr(config,"saved"))

@app.command()
def price(product:str):
    estimate=PriceService().estimate(product)
    if not estimate: fail("Aucun prix externe trouvé." if load_config().language=="fr" else "No external price found."); raise typer.Exit(1)
    table=Table(title=f"Prix — {product}"); table.add_column("Prix observé"); table.add_column("Unité"); table.add_column("Conditionnement"); table.add_column("Confiance"); table.add_row(f"{estimate.price:.2f} €",estimate.price_per or "—",f"{estimate.package_quantity:g} {estimate.package_unit}" if estimate.package_quantity else "—",estimate.confidence); console.print(table)

@app.command()
def recipe(day:str):
    config=load_config(); db=Database(); saved=db.load_latest_plan(("accepted","draft","paused"))
    if not saved: fail(tr(config,"no_plan")); raise typer.Exit(1)
    plan_id,_,meal_plan=saved; target=next((m for m in meal_plan.meals if m.day.casefold()==day.casefold()),None)
    if not target: fail("Jour introuvable." if config.language=="fr" else "Day not found."); raise typer.Exit(1)
    inventory=db.list_inventory(); shopping=build_shopping_list(meal_plan,inventory); generated=generate_recipe(create_provider(config.llm),config,target,inventory,shopping); db.save_recipe(plan_id,target.day,generated); console.print(Panel(f"[bold]{generated.name}[/bold]\n{generated.description}\n\n"+"\n".join(f"{i+1}. {s}" for i,s in enumerate(generated.steps)),title=tr(config,"recipe"),border_style="yellow"))

@app.command()
def cook(day:str):
    config=load_config(); db=Database(); saved=db.load_latest_plan(("accepted",))
    if not saved: fail(tr(config,"no_plan")); raise typer.Exit(1)
    plan_id,_,meal_plan=saved; target=next((m for m in meal_plan.meals if m.day.casefold()==day.casefold()),None)
    if not target: fail("Jour introuvable." if config.language=="fr" else "Day not found."); raise typer.Exit(1)
    recipe_data=db.load_recipe(plan_id,target.day)
    if not recipe_data:
        inventory=db.list_inventory(); recipe_data=generate_recipe(create_provider(config.llm),config,target,inventory,build_shopping_list(meal_plan,inventory)); db.save_recipe(plan_id,target.day,recipe_data)
    console.print(Panel(f"[bold]{recipe_data.name}[/bold]",title="COOKING MODE",border_style="yellow"))
    for i,step in enumerate(recipe_data.steps,1): console.print(Panel(f"Étape {i}/{len(recipe_data.steps)}\n{step}" if config.language=="fr" else f"Step {i}/{len(recipe_data.steps)}\n{step}")); typer.prompt("Entrée pour continuer",default="",show_default=False)

if __name__=="__main__": app()
