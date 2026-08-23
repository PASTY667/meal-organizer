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
    "fr": {"plan":"Plan de la semaine","day":"Jour","meal":"Repas","description":"Description","ingredients":"Ingrédients","shopping":"Liste de courses","purchase":"Prix d'achat","total":"Total des achats","pause":"Plan mis en pause. Reprends avec --resume.","saved":"Plan enregistré.","question":"Question","accept":"valider","quit":"quitter","no_inventory":"Ajoute d'abord des produits avec 'meal-organizer inventory add'.","no_plan":"Aucun plan enregistré.","recipe":"Recette","meals":"Plats de la semaine","cost_unknown":"prix indisponible","stock":"Déjà en stock","generate":"Générer la recette","cook":"Mode cuisine","replace":"remplacer","help":"valider, pause, remplacer <jour> <déjeuner|dîner>, question <jour> <déjeuner|dîner>, quitter"},
    "en": {"plan":"Weekly meal plan","day":"Day","meal":"Meal","description":"Description","ingredients":"Ingredients","shopping":"Shopping list","purchase":"Purchase price","total":"Total purchases","pause":"Plan paused. Resume with --resume.","saved":"Plan saved.","question":"Question","accept":"accept","quit":"quit","no_inventory":"Add inventory first with 'meal-organizer inventory add'.","no_plan":"No saved plan.","recipe":"Recipe","meals":"Weekly meals","cost_unknown":"price unavailable","stock":"Already in stock","generate":"Generate recipe","cook":"Cooking mode","replace":"replace","help":"accept, pause, replace <day> <lunch|dinner>, question <day> <lunch|dinner>, quit"},
}
DAYS={"fr":["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"],"en":["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]}

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
            table=Table(title="Modèles Ollama" if language=="fr" else "Ollama models"); table.add_column("Model")
            for model in models: table.add_row(model)
            console.print(table)
        model=typer.prompt("Modèle Ollama" if language=="fr" else "Ollama model",default=current.model if current.model in models else (models[0] if models else current.model)); return LLMConfig(provider="ollama",model=model,ollama_host=host,web_search=False)
    model=typer.prompt("Modèle OpenRouter" if language=="fr" else "OpenRouter model",default=current.openrouter_model or "openai/gpt-4o-mini"); api_key=getpass("OpenRouter API key (paste supported): ") or current.openrouter_api_key; web_search=typer.confirm("Activer la recherche web" if language=="fr" else "Enable web search",default=current.web_search)
    return LLMConfig(provider="openrouter",model=current.model,ollama_host=current.ollama_host,openrouter_model=model,openrouter_api_key=api_key,web_search=web_search)

@app.command()
def setup():
    current=load_config(); console.print(Panel.fit("[bold]MEAL ORGANIZER[/bold]",border_style="cyan")); language=choose_language(current.language)
    name=typer.prompt("Nom" if language=="fr" else "Name",default=current.name); budget=typer.prompt("Budget hebdomadaire (€)" if language=="fr" else "Weekly budget (€)",default=current.weekly_budget,type=float); servings=typer.prompt("Personnes" if language=="fr" else "Servings",default=current.servings,type=int)
    allergies=typer.prompt("Allergies",default=", ".join(current.allergies)); dislikes=typer.prompt("Aliments à éviter" if language=="fr" else "Foods to avoid",default=", ".join(current.dislikes)); equipment=typer.prompt("Équipement" if language=="fr" else "Equipment",default=", ".join(current.equipment)); llm=choose_llm(current.llm,language)
    config=UserConfig(name=name,language=language,weekly_budget=budget,servings=servings,allergies=[x.strip() for x in allergies.split(",") if x.strip()],dislikes=[x.strip() for x in dislikes.split(",") if x.strip()],equipment=[x.strip() for x in equipment.split(",") if x.strip()],llm=llm); save_config(config); Database(); ok(f"Configuration enregistrée → {ENV_PATH}" if language=="fr" else f"Configuration saved → {ENV_PATH}")

@app.command()
def doctor():
    config=load_config(); table=Table(title="Vérification système" if config.language=="fr" else "System check"); table.add_column("Component"); table.add_column("Status"); table.add_column("Details"); table.add_row("Config","[green]OK[/green]",str(ENV_PATH)); table.add_row("SQLite","[green]OK[/green]","local")
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

def _meal_for(plan:MealPlan, day:str, meal:str)->PlannedMeal|None:
    aliases={"lunch":{"lunch","déjeuner","dejeuner"},"dinner":{"dinner","dîner","diner"}}
    wanted=aliases.get(meal.casefold(),{meal.casefold()})
    return next((m for m in plan.meals if m.day.casefold()==day.casefold() and m.meal.casefold() in wanted),None)

def _show_week(config,plan):
    table=Table(title=tr(config,"meals"),expand=True); table.add_column(tr(config,"day"),width=11); table.add_column(tr(config,"meal"),width=11); table.add_column("Plat" if config.language=="fr" else "Dish",width=30); table.add_column(tr(config,"description"),ratio=2)
    for meal in plan.meals: table.add_row(meal.day,meal.meal,meal.name,meal.description)
    console.print(table)

def _show_shopping(config,shopping,total,budget):
    table=Table(title=tr(config,"shopping")); table.add_column(tr(config,"ingredients")); table.add_column("Qté" if config.language=="fr" else "Qty",justify="right"); table.add_column(tr(config,"purchase"),justify="right")
    for item in shopping: table.add_row(item.name,f"{item.quantity:g} {item.unit}",f"{item.estimated_cost:.2f} €" if item.estimated_cost is not None else tr(config,"cost_unknown"))
    console.print(table)
    label=f"{tr(config,'total')}: {total:.2f} € / {budget:.2f} €" if shopping else ("Aucun achat nécessaire : le stock couvre le plan." if config.language=="fr" else "No purchases needed: inventory covers the plan.")
    console.print(Panel(f"[bold]{label}[/bold]",border_style="green" if total<=budget else "red"))

def _show_day_recipe_menu(config,day,plan):
    choices=[m for m in plan.meals if m.day.casefold()==day.casefold()]
    if not choices: return None
    table=Table(title=day); table.add_column("#"); table.add_column(tr(config,"meal")); table.add_column("Plat" if config.language=="fr" else "Dish")
    for i,m in enumerate(choices,1): table.add_row(str(i),m.meal,m.name)
    console.print(table); choice=typer.prompt("Choisis un repas (1/2)" if config.language=="fr" else "Choose a meal (1/2)",type=int)
    return choices[choice-1] if 1<=choice<=len(choices) else None

@app.command()
def plan(resume:bool=typer.Option(False,"--resume",help="Resume the latest paused/draft plan")):
    config=load_config(); db=Database(); inventory=db.list_inventory()
    if not inventory: fail(tr(config,"no_inventory")); raise typer.Exit(1)
    provider=create_provider(config.llm); pricing=PriceService(); saved=db.load_latest_plan() if resume else None
    if saved:
        plan_id,_,meal_plan=saved; ok("Plan repris." if config.language=="fr" else "Plan resumed.")
    else:
        with console.status("Analyse globale de la semaine et génération du plan..." if config.language=="fr" else "Globally optimizing the week and generating the plan..."):
            try: meal_plan=generate_plan(provider,config,inventory)
            except Exception as exc: fail(str(exc)); raise typer.Exit(1) from exc
        plan_id=db.save_plan(meal_plan,"draft")
    while True:
        price_plan(meal_plan,config,inventory,enforce_budget=False,pricing=pricing); shopping=build_shopping_list(meal_plan,inventory,pricing)
        _show_week(config,meal_plan); _show_shopping(config,shopping,meal_plan.shopping_cost,config.weekly_budget)
        action=typer.prompt(f"Action ({tr(config,'help')})",default=tr(config,"accept")).strip(); parts=action.split(maxsplit=2); command=parts[0].casefold()
        if command in {"valider","accept","ok"}:
            db.save_plan(meal_plan,"accepted",plan_id); ok(tr(config,"saved")); return
        if command in {"pause","p"}:
            db.save_plan(meal_plan,"paused",plan_id); ok(tr(config,"pause")); return
        if command in {"quitter","quit","q"}:
            db.save_plan(meal_plan,"paused",plan_id); ok(tr(config,"pause")); return
        if command in {"remplacer","replace"} and len(parts)>=3:
            target=_meal_for(meal_plan,parts[1],parts[2])
            if not target: warn("Repas introuvable." if config.language=="fr" else "Meal not found."); continue
            reason=typer.prompt("Pourquoi le remplacer ?" if config.language=="fr" else "Why replace it?",default="")
            with console.status("Recherche d'une alternative..." if config.language=="fr" else "Finding an alternative..."):
                replacement=replace_meal(provider,config,target,inventory,reason); meal_plan.meals[meal_plan.meals.index(target)]=replacement
            db.save_plan(meal_plan,"draft",plan_id); continue
        if command in {"question","ask"} and len(parts)>=3:
            target=_meal_for(meal_plan,parts[1],parts[2])
            if not target: warn("Repas introuvable." if config.language=="fr" else "Meal not found."); continue
            question=typer.prompt(tr(config,"question")); console.print(Panel(provider.generate(build_question_request(config,target,question)),title=tr(config,"question"),border_style="cyan")); continue
        warn("Commande inconnue." if config.language=="fr" else "Unknown command.")

@app.command("meals")
def meals():
    config=load_config(); saved=Database().load_latest_plan(("accepted","draft","paused"))
    if not saved: fail(tr(config,"no_plan")); raise typer.Exit(1)
    _show_week(config,saved[2])

@app.command()
def recipe(day:str,meal:str):
    config=load_config(); db=Database(); saved=db.load_latest_plan(("accepted","draft","paused"))
    if not saved: fail(tr(config,"no_plan")); raise typer.Exit(1)
    plan_id,_,meal_plan=saved; target=_meal_for(meal_plan,day,meal)
    if not target: fail("Repas introuvable." if config.language=="fr" else "Meal not found."); raise typer.Exit(1)
    inventory=db.list_inventory(); shopping=build_shopping_list(meal_plan,inventory); provider=create_provider(config.llm)
    with console.status("Recherche de recettes et génération..." if config.language=="fr" else "Researching recipes and generating..."):
        generated=generate_recipe(provider,config,target,inventory,shopping)
    key=f"{target.day}:{target.meal}"; db.save_recipe(plan_id,key,generated)
    console.print(Panel(f"[bold]{generated.name}[/bold]\n{generated.description}\n\nPréparation: {generated.preparation_minutes} min · Cuisson: {generated.cooking_minutes} min" if config.language=="fr" else f"[bold]{generated.name}[/bold]\n{generated.description}\n\nPrep: {generated.preparation_minutes} min · Cook: {generated.cooking_minutes} min",title=tr(config,"recipe"),border_style="yellow"))
    console.print("Utilise 'meal-organizer cook <jour> <déjeuner|dîner>' pour cuisiner étape par étape." if config.language=="fr" else "Use 'meal-organizer cook <day> <lunch|dinner>' to cook step by step.")

@app.command()
def cook(day:str,meal:str):
    config=load_config(); db=Database(); saved=db.load_latest_plan(("accepted",))
    if not saved: fail("Le plan doit être validé avant le mode cuisine." if config.language=="fr" else "The plan must be accepted before cooking mode."); raise typer.Exit(1)
    plan_id,_,meal_plan=saved; target=_meal_for(meal_plan,day,meal)
    if not target: fail("Repas introuvable." if config.language=="fr" else "Meal not found."); raise typer.Exit(1)
    key=f"{target.day}:{target.meal}"; recipe_data=db.load_recipe(plan_id,key)
    if not recipe_data:
        inventory=db.list_inventory(); shopping=build_shopping_list(meal_plan,inventory)
        with console.status("Génération de la recette..." if config.language=="fr" else "Generating recipe..."): recipe_data=generate_recipe(create_provider(config.llm),config,target,inventory,shopping)
        db.save_recipe(plan_id,key,recipe_data)
    console.print(Panel(f"[bold]{recipe_data.name}[/bold]",title=tr(config,"cook"),border_style="yellow"))
    for i,step in enumerate(recipe_data.steps,1):
        console.print(Panel(f"[bold]Étape {i}/{len(recipe_data.steps)}[/bold]\n{step}" if config.language=="fr" else f"[bold]Step {i}/{len(recipe_data.steps)}[/bold]\n{step}",border_style="cyan"))
        if i<len(recipe_data.steps):
            action=typer.prompt("Entrée pour continuer, q pour quitter",default="",show_default=False)
            if action.casefold()=="q": return
    ok("Bon appétit." if config.language=="fr" else "Enjoy your meal.")

@app.command()
def price(product:str):
    config=load_config(); estimate=PriceService().estimate(product)
    if not estimate: fail("Aucun prix externe fiable trouvé." if config.language=="fr" else "No reliable external price found."); raise typer.Exit(1)
    table=Table(title=f"Prix — {product}"); table.add_column("Prix"); table.add_column("Unité"); table.add_column("Conditionnement"); table.add_column("Confiance"); table.add_row(f"{estimate.price:.2f} €",estimate.price_per or "—",f"{estimate.package_quantity:g} {estimate.package_unit}" if estimate.package_quantity else "—",estimate.confidence); console.print(table)

if __name__=="__main__": app()
