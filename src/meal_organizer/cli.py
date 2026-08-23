from getpass import getpass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import ENV_PATH, LLMConfig, UserConfig, check_ollama, load_config, save_config
from .db import Database
from .llm import LLMRequest, create_provider
from .models import MealPlan
from .planning import (
    build_question_request,
    build_shopping_list,
    generate_plan,
    generate_recipe,
    price_plan,
    replace_meal,
)
from .pricing import PriceService

app = typer.Typer(help="Meal Organizer", no_args_is_help=True)
console = Console()

T = {
    "fr": {
        "name": "Nom", "budget": "Budget hebdomadaire (€)", "servings": "Personnes",
        "allergies": "Allergies (séparées par des virgules)", "dislikes": "Aliments à éviter (séparés par des virgules)",
        "equipment": "Équipement (séparé par des virgules)", "language": "Langue", "provider": "Fournisseur LLM",
        "web": "Activer la recherche web pour les recettes", "saved": "Configuration enregistrée", "plan": "Plan de la semaine", "shopping": "Liste de courses",
        "meal": "Repas", "description": "Description", "ingredients": "Ingrédients", "cost": "Coût estimé",
        "total": "Total courses estimé", "action": "Action", "help": "valider, pause, remplacer <jour>, question <jour>, quitter",
        "paused": "Plan mis en pause. Tu pourras reprendre avec --resume.", "accepted": "Plan enregistré.", "recipe": "Recette",
        "question": "Question", "replace_reason": "Pourquoi veux-tu remplacer ce repas ?", "no_plan": "Aucun plan en cours. Lance d'abord 'meal-organizer plan'.",
        "day": "Jour", "steps": "Étapes",
    },
    "en": {
        "name": "Name", "budget": "Weekly budget (€)", "servings": "Servings",
        "allergies": "Allergies (comma separated)", "dislikes": "Foods to avoid (comma separated)",
        "equipment": "Equipment (comma separated)", "language": "Language", "provider": "LLM provider",
        "web": "Enable web search for recipes", "saved": "Configuration saved", "plan": "Weekly meal plan", "shopping": "Shopping list",
        "meal": "Meal", "description": "Description", "ingredients": "Ingredients", "cost": "Estimated cost",
        "total": "Estimated shopping total", "action": "Action", "help": "accept, pause, replace <day>, question <day>, quit",
        "paused": "Plan paused. Resume later with --resume.", "accepted": "Plan saved.", "recipe": "Recipe",
        "question": "Question", "replace_reason": "Why do you want to replace this meal?", "no_plan": "No active plan. Run 'meal-organizer plan' first.",
        "day": "Day", "steps": "Steps",
    },
}


def tr(config: UserConfig, key: str) -> str:
    return T[config.language][key]


def ok(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")


def fail(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] {message}")


def warn(message: str) -> None:
    console.print(f"[bold yellow]![/bold yellow] {message}")


def choose_language(current: str) -> str:
    choice = typer.prompt("Language / Langue [fr/en]", default=current).strip().lower()
    while choice not in {"fr", "en"}:
        choice = typer.prompt("Language / Langue [fr/en]", default=current).strip().lower()
    return choice


def choose_llm(current: LLMConfig, language: str) -> LLMConfig:
    title, subtitle = ({"fr": ("Configuration LLM", "Choisis comment générer les plans."), "en": ("LLM CONFIGURATION", "Choose how Meal Organizer should generate plans.")})[language]
    console.print(Panel.fit(f"[bold]{title}[/bold]\n{subtitle}", border_style="cyan"))
    provider = typer.prompt(tr(UserConfig(language=language), "provider"), default=current.provider).strip().lower()
    while provider not in {"ollama", "openrouter"}:
        warn("Choisis ollama ou openrouter." if language == "fr" else "Choose ollama or openrouter.")
        provider = typer.prompt(tr(UserConfig(language=language), "provider"), default=current.provider).strip().lower()
    if provider == "ollama":
        host = typer.prompt("URL Ollama", default=current.ollama_host)
        reachable, models = check_ollama(host)
        if reachable:
            ok("Ollama est accessible." if language == "fr" else "Ollama is reachable.")
            if models:
                table = Table(title="Modèles Ollama" if language == "fr" else "Ollama models")
                table.add_column("Model")
                for model in models: table.add_row(model)
                console.print(table)
                default_model = current.model if current.model in models else models[0]
            else:
                warn("Aucun modèle Ollama installé." if language == "fr" else "No Ollama models installed.")
                default_model = current.model
        else:
            warn("Ollama n'est pas accessible." if language == "fr" else "Ollama is not reachable.")
            default_model = current.model
        model = typer.prompt("Modèle Ollama" if language == "fr" else "Ollama model", default=default_model)
        return LLMConfig(provider="ollama", model=model, ollama_host=host, web_search=False)
    model = typer.prompt("Modèle OpenRouter" if language == "fr" else "OpenRouter model", default=current.openrouter_model or "openai/gpt-4o-mini")
    if current.openrouter_api_key:
        console.print("[dim]Clé existante : Entrée pour la conserver." if language == "fr" else "[dim]Existing key: press Enter to keep it.")
    api_key = getpass("OpenRouter API key (paste supported): ") or current.openrouter_api_key
    web_search = typer.confirm(tr(UserConfig(language=language), "web"), default=current.web_search)
    return LLMConfig(provider="openrouter", model=current.model, ollama_host=current.ollama_host, openrouter_model=model, openrouter_api_key=api_key, web_search=web_search)


@app.command()
def setup() -> None:
    current = load_config()
    console.print(Panel.fit(f"[bold]MEAL ORGANIZER[/bold]\nSetup · {'existing configuration' if ENV_PATH.exists() else 'new configuration'}", border_style="cyan"))
    language = choose_language(current.language); local = UserConfig(language=language)
    name = typer.prompt(tr(local, "name"), default=current.name)
    budget = typer.prompt(tr(local, "budget"), default=current.weekly_budget, type=float)
    servings = typer.prompt(tr(local, "servings"), default=current.servings, type=int)
    allergies = typer.prompt(tr(local, "allergies"), default=", ".join(current.allergies))
    dislikes = typer.prompt(tr(local, "dislikes"), default=", ".join(current.dislikes))
    equipment = typer.prompt(tr(local, "equipment"), default=", ".join(current.equipment))
    llm = choose_llm(current.llm, language)
    config = UserConfig(name=name, language=language, weekly_budget=budget, servings=servings, allergies=[x.strip() for x in allergies.split(",") if x.strip()], dislikes=[x.strip() for x in dislikes.split(",") if x.strip()], equipment=[x.strip() for x in equipment.split(",") if x.strip()], llm=llm)
    save_config(config); Database(); ok(f"{tr(config, 'saved')} → {ENV_PATH}")


@app.command()
def doctor() -> None:
    config = load_config(); table = Table(title="System check")
    table.add_column("Component"); table.add_column("Status"); table.add_column("Details")
    table.add_row("Python", "[green]OK[/green]", "Supported runtime"); table.add_row("SQLite", "[green]OK[/green]", "Local database"); table.add_row("Config", "[green]OK[/green]", f"{config.llm.provider} / {ENV_PATH}")
    if config.llm.provider == "openrouter": table.add_row("Web search", "[green]ON[/green]" if config.llm.web_search else "[dim]OFF[/dim]", "OpenRouter")
    try:
        provider = create_provider(config.llm); provider.generate(LLMRequest(system="Reply with OK only.", prompt="OK")); table.add_row("LLM", "[green]OK[/green]", config.llm.provider)
    except Exception as exc: table.add_row("LLM", "[yellow]WARN[/yellow]", str(exc)[:120])
    console.print(table)


inventory_app = typer.Typer(help="Manage inventory"); app.add_typer(inventory_app, name="inventory")


@inventory_app.command("list")
def inventory_list() -> None:
    config = load_config(); items = Database().list_inventory(); table = Table(title="Inventaire" if config.language == "fr" else "Inventory")
    for column in (["Produit", "Quantité", "Unité", "Emplacement"] if config.language == "fr" else ["Product", "Quantity", "Unit", "Location"]): table.add_column(column)
    for item in items: table.add_row(item.name, f"{item.quantity:g}", item.unit, item.location)
    console.print(table)
    if not items: console.print("[dim]Inventaire vide.[/dim]" if config.language == "fr" else "[dim]Inventory is empty.[/dim]")


@inventory_app.command("add")
def inventory_add(name: str, quantity: float, unit: str = "unit", location: str = "fridge") -> None:
    Database().upsert_inventory(name, quantity, unit, location); ok(f"{name} updated.")


@inventory_app.command("remove")
def inventory_remove(name: str) -> None:
    if Database().remove_inventory(name): ok(f"{name} removed.")
    else: fail(f"{name} was not found."); raise typer.Exit(1)


def _show_plan(config: UserConfig, plan: MealPlan, shopping) -> None:
    table = Table(title=tr(config, "plan"), expand=True); table.add_column(tr(config, "day"), width=10); table.add_column(tr(config, "meal"), width=10); table.add_column(tr(config, "description"), ratio=2); table.add_column(tr(config, "ingredients"), ratio=2); table.add_column(tr(config, "cost"), justify="right", width=12)
    for meal in plan.meals:
        ingredients = ", ".join(f"{i.quantity:g}{i.unit} {i.name}" for i in meal.ingredients); cost = f"{meal.estimated_cost:.2f} €" if meal.estimated_cost is not None else "n/a"
        table.add_row(meal.day, meal.meal, f"[bold]{meal.name}[/bold]\n{meal.description}", ingredients, cost)
    console.print(table)
    shop = Table(title=tr(config, "shopping")); shop.add_column(tr(config, "ingredients")); shop.add_column("Qty", justify="right"); shop.add_column(tr(config, "cost"), justify="right")
    for item in shopping: shop.add_row(item.name, f"{item.quantity:g} {item.unit}", f"{item.estimated_cost:.2f} €" if item.estimated_cost is not None else "n/a")
    console.print(shop); console.print(Panel(f"[bold]{tr(config, 'total')}: {plan.shopping_cost:.2f} € / {config.weekly_budget:.2f} €[/bold]", border_style="green"))


@app.command()
def plan(resume: bool = typer.Option(False, "--resume", help="Resume the latest paused/draft plan")) -> None:
    config = load_config(); db = Database(); inventory = db.list_inventory(); provider = create_provider(config.llm); existing = db.load_latest_plan() if resume else None
    if existing:
        plan_id, _, meal_plan = existing; meal_plan = price_plan(meal_plan, config, inventory); ok("Plan resumed." if config.language == "en" else "Plan repris.")
    else:
        with console.status("Génération du plan..." if config.language == "fr" else "Generating plan..."):
            try: meal_plan = generate_plan(provider, config, inventory)
            except Exception as exc: fail(str(exc)); raise typer.Exit(1) from exc
        plan_id = db.save_plan(meal_plan, "draft")
    while True:
        shopping = build_shopping_list(meal_plan, inventory); _show_plan(config, meal_plan, shopping)
        action = typer.prompt(tr(config, "action") + f" ({tr(config, 'help')})", default="accept").strip(); parts = action.split(maxsplit=1); command = parts[0].lower()
        if command in {"accept", "valider", "ok"}: db.save_plan(meal_plan, "accepted", plan_id); ok(tr(config, "accepted")); return
        if command in {"pause", "pausee", "quit", "quitter", "q"}: db.save_plan(meal_plan, "paused", plan_id); ok(tr(config, "paused")); return
        if command in {"replace", "remplacer"}:
            day = parts[1] if len(parts) > 1 else typer.prompt(tr(config, "day")); candidates = [m for m in meal_plan.meals if m.day.casefold() == day.casefold()]
            if not candidates: warn("Jour introuvable." if config.language == "fr" else "Day not found."); continue
            target = candidates[0]; reason = typer.prompt(tr(config, "replace_reason"), default="")
            with console.status("Recherche d'une alternative..." if config.language == "fr" else "Finding an alternative..."):
                target_new = replace_meal(provider, config, target, inventory, reason); target_new.estimated_cost = None; meal_plan.meals[meal_plan.meals.index(target)] = target_new; meal_plan = price_plan(meal_plan, config, inventory)
            continue
        if command in {"question", "ask", "qst"}:
            day_and_question = parts[1] if len(parts) > 1 else typer.prompt(tr(config, "day")); day, _, question = day_and_question.partition(" "); target = next((m for m in meal_plan.meals if m.day.casefold() == day.casefold()), None)
            if not target: warn("Jour introuvable." if config.language == "fr" else "Day not found."); continue
            if not question: question = typer.prompt(tr(config, "question"))
            console.print(Panel(provider.generate(build_question_request(config, target, question)), title=tr(config, "question"), border_style="cyan")); continue
        warn("Commande inconnue." if config.language == "fr" else "Unknown command.")


@app.command()
def recipe(day: str) -> None:
    config = load_config(); db = Database(); saved = db.load_latest_plan(("accepted", "draft", "paused"))
    if not saved: fail(tr(config, "no_plan")); raise typer.Exit(1)
    plan_id, _, meal_plan = saved; target = next((m for m in meal_plan.meals if m.day.casefold() == day.casefold()), None)
    if not target: fail("Jour introuvable." if config.language == "fr" else "Day not found."); raise typer.Exit(1)
    inventory = db.list_inventory(); shopping = build_shopping_list(meal_plan, inventory); provider = create_provider(config.llm)
    with console.status("Recherche et génération de la recette..." if config.language == "fr" else "Researching and generating recipe..."):
        generated = generate_recipe(provider, config, target, inventory, shopping)
    db.save_recipe(plan_id, target.day, generated)
    console.print(Panel(f"[bold]{generated.name}[/bold]\n{generated.description}", title=tr(config, "recipe"), border_style="green"))
    table = Table(title=tr(config, "ingredients")); table.add_column("Qty"); table.add_column("Ingredient")
    for item in generated.ingredients: table.add_row(f"{item.quantity:g} {item.unit}", item.name)
    console.print(table); console.print(Panel("\n".join(f"[bold]{i}.[/bold] {step}" for i, step in enumerate(generated.steps, 1)), title=tr(config, "steps"), border_style="yellow"))
    if generated.sources: console.print("\n".join(f"Source: {source}" for source in generated.sources))


@app.command("recipe-ask")
def recipe_ask(day: str, question: str) -> None:
    from .planning import build_recipe_question_request
    config = load_config(); db = Database(); saved = db.load_latest_plan(("accepted", "draft", "paused"))
    if not saved: fail(tr(config, "no_plan")); raise typer.Exit(1)
    plan_id, _, _ = saved; stored = db.load_recipe(plan_id, day)
    if not stored: recipe(day); stored = db.load_recipe(plan_id, day)
    if not stored: raise typer.Exit(1)
    provider = create_provider(config.llm); answer = provider.generate(build_recipe_question_request(config, stored, question)); console.print(Panel(answer, title=tr(config, "question"), border_style="cyan"))


@app.command()
def cook(day: str) -> None:
    config = load_config(); db = Database(); saved = db.load_latest_plan(("accepted",))
    if not saved: fail(tr(config, "no_plan")); raise typer.Exit(1)
    plan_id, _, _ = saved; stored = db.load_recipe(plan_id, day)
    if not stored: recipe(day); stored = db.load_recipe(plan_id, day)
    if not stored: raise typer.Exit(1)
    console.print(Panel.fit(f"[bold]{stored.name}[/bold]", title="COOKING MODE"))
    for index, step in enumerate(stored.steps, 1):
        console.print(Panel(step, title=f"{index}/{len(stored.steps)}", border_style="yellow"))
        if index < len(stored.steps): typer.prompt("Enter" if config.language == "en" else "Entrée", default="", show_default=False)
    ok("Finished." if config.language == "en" else "Terminé.")


@app.command()
def price(product: str, quantity: float = typer.Option(1, "--quantity", "-q"), unit: str = typer.Option("unit", "--unit", "-u")) -> None:
    estimate = PriceService().estimate(product)
    if not estimate: fail("No reliable external price was found."); raise typer.Exit(1)
    cost = estimate.cost_for(quantity, unit); table = Table(title=f"Price: {product}"); table.add_column("Observed price"); table.add_column("Cost for quantity"); table.add_column("Source"); table.add_column("Confidence"); table.add_row(f"{estimate.price:.2f} €", f"{cost:.2f} €" if cost is not None else "n/a", estimate.source, estimate.confidence); console.print(table)


if __name__ == "__main__":
    app()
