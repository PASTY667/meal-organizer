from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import LLMConfig, UserConfig, load_config, save_config
from .db import Database
from .llm import create_provider, LLMRequest
from .pricing import PriceService

app = typer.Typer(help="Plan simple, balanced and affordable meals.", no_args_is_help=True)
console = Console()


def ok(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")


def fail(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] {message}")


@app.command()
def setup() -> None:
    """Create or update the local user configuration."""
    current = load_config()
    console.print(Panel.fit("[bold]MEAL ORGANIZER[/bold]\nConfiguration", border_style="cyan"))
    name = typer.prompt("Name", default=current.name)
    budget = typer.prompt("Weekly budget (€)", default=current.weekly_budget, type=float)
    servings = typer.prompt("Servings", default=current.servings, type=int)
    allergies = typer.prompt("Allergies (comma separated)", default=", ".join(current.allergies))
    dislikes = typer.prompt("Foods to avoid (comma separated)", default=", ".join(current.dislikes))
    equipment = typer.prompt("Equipment (comma separated)", default=", ".join(current.equipment))
    provider = typer.prompt("LLM provider (ollama/openrouter)", default=current.llm.provider)
    model = typer.prompt("Ollama model", default=current.llm.model)
    ollama_host = typer.prompt("Ollama host", default=current.llm.ollama_host)
    openrouter_model = typer.prompt("OpenRouter model", default=current.llm.openrouter_model)
    api_key = typer.prompt("OpenRouter API key (leave empty to keep current)", default="", hide_input=True)
    if not api_key:
        api_key = current.llm.openrouter_api_key

    config = UserConfig(
        name=name,
        weekly_budget=budget,
        servings=servings,
        allergies=[x.strip() for x in allergies.split(",") if x.strip()],
        dislikes=[x.strip() for x in dislikes.split(",") if x.strip()],
        equipment=[x.strip() for x in equipment.split(",") if x.strip()],
        llm=LLMConfig(
            provider=provider.strip().lower(),
            model=model,
            ollama_host=ollama_host,
            openrouter_model=openrouter_model,
            openrouter_api_key=api_key,
        ),
    )
    save_config(config)
    Database()
    ok("Configuration saved locally.")


@app.command()
def doctor() -> None:
    """Check local configuration and optional LLM connectivity."""
    config = load_config()
    table = Table(title="System check", show_header=True)
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Details")
    table.add_row("Python", "[green]OK[/green]", "Supported runtime")
    table.add_row("SQLite", "[green]OK[/green]", "Local database available")
    table.add_row("Config", "[green]OK[/green]", config.llm.provider)
    try:
        provider = create_provider(config.llm)
        provider.generate(LLMRequest(system="Reply with OK only.", prompt="OK"))
        table.add_row("LLM", "[green]OK[/green]", config.llm.provider)
    except Exception as exc:
        table.add_row("LLM", "[yellow]WARN[/yellow]", str(exc)[:100])
    console.print(table)


inventory_app = typer.Typer(help="Manage fridge, cupboard and freezer inventory.")
app.add_typer(inventory_app, name="inventory")


@inventory_app.command("list")
def inventory_list() -> None:
    """Display the current inventory."""
    items = Database().list_inventory()
    table = Table(title="Inventory")
    table.add_column("Product")
    table.add_column("Quantity", justify="right")
    table.add_column("Unit")
    table.add_column("Location")
    for item in items:
        table.add_row(item.name, f"{item.quantity:g}", item.unit, item.location)
    console.print(table)
    if not items:
        console.print("[dim]Inventory is empty.[/dim]")


@inventory_app.command("add")
def inventory_add(name: str, quantity: float, unit: str = "unit", location: str = "fridge") -> None:
    """Add or replace an inventory item."""
    Database().upsert_inventory(name, quantity, unit, location)
    ok(f"{name} updated.")


@inventory_app.command("remove")
def inventory_remove(name: str) -> None:
    """Remove an inventory item."""
    if Database().remove_inventory(name):
        ok(f"{name} removed.")
    else:
        fail(f"{name} was not found.")
        raise typer.Exit(1)


@app.command()
def price(product: str) -> None:
    """Estimate a product price from external data."""
    estimate = PriceService().estimate(product)
    if not estimate:
        fail("No reliable external price was found.")
        raise typer.Exit(1)
    table = Table(title=f"Price estimate: {product}")
    table.add_column("Price")
    table.add_column("Source")
    table.add_column("Confidence")
    table.add_column("Samples")
    table.add_row(f"{estimate.price:.2f} {estimate.currency}", estimate.source, estimate.confidence, str(estimate.samples))
    console.print(table)


@app.command()
def plan() -> None:
    """Generate a weekly plan using the configured LLM."""
    config = load_config()
    inventory = Database().list_inventory()
    if not inventory:
        fail("Inventory is empty. Add ingredients first with 'meal-organizer inventory add'.")
        raise typer.Exit(1)
    provider = create_provider(config.llm)
    inventory_text = ", ".join(f"{x.quantity:g} {x.unit} {x.name}" for x in inventory)
    system = (
        "You are a meal planning assistant. Respect allergies as hard constraints. "
        "Never recommend an explicitly disliked food. Consider equipment and budget. "
        "Return concise Markdown with a 7-day table and a shopping list. Clearly label "
        "estimated costs and never claim a price is exact."
    )
    prompt = (
        f"Servings: {config.servings}\nBudget: {config.weekly_budget:.2f} EUR/week\n"
        f"Allergies: {', '.join(config.allergies) or 'none'}\n"
        f"Foods to avoid: {', '.join(config.dislikes) or 'none'}\n"
        f"Equipment: {', '.join(config.equipment) or 'basic stovetop'}\n"
        f"Inventory: {inventory_text}"
    )
    with console.status("Generating meal plan..."):
        try:
            result = provider.generate(LLMRequest(system=system, prompt=prompt))
        except Exception as exc:
            fail(f"LLM request failed: {exc}")
            raise typer.Exit(1) from exc
    console.print(Panel(result, title="Weekly meal plan", border_style="green"))


@app.command()
def cook(recipe: Optional[str] = typer.Argument(None)) -> None:
    """Start interactive cooking mode for a recipe description."""
    if not recipe:
        recipe = typer.prompt("Recipe")
    console.print(Panel.fit(f"[bold]COOKING MODE[/bold]\n{recipe}", border_style="yellow"))
    console.print("Enter each step as you cook. Use Ctrl+C to exit.")
    typer.prompt("When ready, press Enter", default="", show_default=False)
    console.print("[green]Ready. The recipe step-by-step UI will be connected to generated recipes in the next milestone.[/green]")


if __name__ == "__main__":
    app()
