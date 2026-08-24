# Meal Organizer

Meal Organizer is a local-first Python CLI for planning affordable, balanced weekly meals from your inventory, preferences, equipment and budget. It generates a complete weekly plan, builds a shopping list, estimates purchase costs, generates recipes on demand and provides an interactive cooking mode.

The project is designed to run on Windows, Linux and macOS and keeps user configuration and local data outside the repository.

## Requirements

Python 3.11 or newer is recommended. Git is only required if you install from the repository and want to update with `git pull`.

The application uses SQLite locally. No database server is required.

For LLM generation, choose one of these two modes:

- Ollama: local inference, no hosted API key required.
- OpenRouter: hosted inference through an OpenRouter API key. Web search can be enabled for recipe research when supported by the selected model/provider configuration.

## Installation

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/PASTY667/meal-organizer.git
cd meal-organizer
python -m venv .venv
```

Activate it.

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Windows CMD:

```cmd
.venv\Scripts\activate.bat
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install Meal Organizer in editable mode:

```bash
python -m pip install -e .
```

Check the CLI is available:

```bash
meal-organizer --help
```

Then run the initial setup wizard:

```bash
meal-organizer setup
```

If you update the repository later, the usual workflow is:

```bash
git pull
python -m pip install -e .
```

## First-time setup

The setup wizard stores configuration in:

```text
~/.meal-organizer/.env
```

On Windows this normally resolves to something similar to:

```text
C:\Users\<user>\.meal-organizer\.env
```

The `.env` file contains your language, budget, servings, preferences, equipment, supermarket reference and LLM configuration. API keys are local configuration and must not be committed to Git.

The setup wizard asks for the following information:

```text
Language
Name
Weekly budget
Servings
Reference supermarket
Allergies
Foods to avoid
Cooking equipment
LLM provider and model
```

Supported reference supermarkets are `leclerc`, `intermarche`, `carrefour`, `auchan` and `generic`.

You can rerun `meal-organizer setup` at any time to update the configuration. Existing values are used as defaults.

## Configure Ollama

Ollama runs the LLM locally on your machine. This is the preferred option if you want local inference and do not want to send prompts to a hosted provider.

Install Ollama from the official website:

```text
https://ollama.com/
```

After installation, verify that Ollama is available:

```bash
ollama --version
```

Pull a model. For example:

```bash
ollama pull qwen3:8b
```

You can inspect installed models with:

```bash
ollama list
```

Ollama normally exposes its local API at:

```text
http://127.0.0.1:11434
```

Run the setup wizard and choose:

```text
LLM provider: ollama
Ollama host: http://127.0.0.1:11434
Ollama model: qwen3:8b
```

The setup wizard attempts to detect Ollama and list the models available locally.

Useful checks:

```bash
meal-organizer doctor
ollama list
```

If the wizard cannot reach Ollama, make sure the Ollama application/service is running and that the configured host is correct.

## Configure OpenRouter

OpenRouter provides access to hosted models through a single API endpoint.

Create an account and API key from:

```text
https://openrouter.ai/
```

Then run:

```bash
meal-organizer setup
```

Choose:

```text
LLM provider: openrouter
OpenRouter model: <your model>
OpenRouter API key: <your key>
Enable web search: yes/no
```

A typical model identifier looks like:

```text
openai/gpt-4o-mini
```

or another model currently available through OpenRouter. Use the exact model identifier exposed by OpenRouter.

The API key is stored in the local `.env` file under `~/.meal-organizer/`. Do not paste it into source files or commit it to Git.

If OpenRouter is configured correctly, check it with:

```bash
meal-organizer doctor
```

## Language

Meal Organizer supports French and English.

The selected language affects the CLI, plan generation, recipe generation and interactive questions.

To change it:

```bash
meal-organizer setup
```

Choose `fr` or `en` in the language prompt.

## Inventory management

The inventory represents what you already have at home. The planner uses it when deciding what to cook and what must actually be purchased.

List the inventory:

```bash
meal-organizer inventory list
```

Add an item:

```bash
meal-organizer inventory add "riz" 500 --unit g --location cupboard
meal-organizer inventory add "oeufs" 6 --unit unit --location fridge
meal-organizer inventory add "beurre" 200 --unit g --location fridge
```

Remove an item:

```bash
meal-organizer inventory remove "oeufs"
```

Update an existing item by adding it again:

```bash
meal-organizer inventory add "oeufs" 4 --unit unit --location fridge
```

Use consistent units whenever possible. Typical values are `g`, `kg`, `ml`, `l` and `unit`.

The planner normalizes common ingredient aliases. For example, variants of rice, eggs, chicken and several pantry products can be matched against inventory so already-owned products are not unnecessarily added to the shopping list.

## Generate a weekly plan

The main command is:

```bash
meal-organizer plan
```

The planner builds a week globally rather than generating isolated meals. The target is exactly 14 meals: lunch and dinner for each day from Monday to Sunday.

The planner considers:

- current inventory
- allergies
- disliked foods
- cooking equipment
- servings
- weekly budget
- recent meal history
- ingredient reuse and waste reduction
- meal variety

The budget is treated as a hard constraint for acceptance. A plan whose calculated shopping basket exceeds the configured budget should not be accepted.

The interactive planning session can pause, resume, replace a meal or answer questions about a meal.

Resume the latest paused/draft plan with:

```bash
meal-organizer plan --resume
```

Accepted plans are timestamped in SQLite. A current accepted plan is considered current for approximately seven days; after that, `meal-organizer plan` can generate the next weekly plan while using recent accepted plans as history to reduce repetition.

## Understand the shopping list

The weekly plan is shown separately from the shopping list.

The shopping list is based on the total ingredient requirements of the week minus what is already available in the inventory. For measurable ingredients, the application attempts to calculate the missing quantity. Pantry staples already in inventory should not be purchased again simply because the recipe expresses the requirement in another unit.

The price shown for a shopping item is intended to represent the purchase cost of the product/packaging required to satisfy the weekly need, not an artificial zero price for inventory items.

Price data are estimates and should be treated as such unless a current retailer observation is available.

## Price lookup

Use:

```bash
meal-organizer price "poulet"
```

The command displays the available price estimate, unit, package information and confidence when supported by the configured pricing backend.

The application distinguishes between the cost of the quantity consumed and the purchase cost of the package actually needed for the shopping basket.

Open Prices is used as an external source when applicable. Retailer-specific reference settings are stored in `.env` and are intended to support retailer-aware pricing logic.

The pricing system must not be interpreted as a guarantee of an exact in-store price. Promotions, store selection, product brands and local availability can change the actual amount paid.

## Recipes

Recipes are generated when requested, rather than embedded directly into the weekly meal table.

Generate a recipe for a planned meal:

```bash
meal-organizer recipe jeudi déjeuner
```

The recipe generator receives the selected meal, current inventory and shopping list. With an LLM/provider configuration that supports web research, the model can use web research to find credible recipe ideas and adapt them to the user's constraints.

Recipes are stored separately from the meal plan in SQLite so the weekly plan stays lightweight and reusable.

## Cooking mode

After a plan has been accepted, use cooking mode to prepare one meal step by step:

```bash
meal-organizer cook jeudi déjeuner
```

The application displays each step separately and waits for confirmation before moving to the next step. Enter `q` when prompted to leave cooking mode.

## Questions and meal replacements

During an interactive planning session, the user can ask questions about a meal or request a replacement.

Examples:

```text
question jeudi déjeuner
remplacer jeudi déjeuner
```

The exact interactive prompt wording follows the selected language.

## System checks

Run:

```bash
meal-organizer doctor
```

This checks the local configuration/database and attempts an LLM connectivity check using the configured provider.

If the LLM check fails, verify the selected provider, model, API key and host.

## Data and configuration locations

User-specific data is kept outside the repository:

```text
~/.meal-organizer/
├── .env
└── meal-organizer.db
```

`meal-organizer.db` contains inventory, meal plans, recipes and related local application state.

Do not commit `.env` or local database files.

## Troubleshooting

### `meal-organizer` is not recognized

Make sure the virtual environment is activated and reinstall the project:

```bash
python -m pip install -e .
```

Then open a new terminal if necessary.

### `ImportError` or stale code after a Git update

Run:

```bash
git pull
python -m pip install -e .
```

If the working tree contains local modifications that conflict with the pull, inspect them before resetting anything.

### Ollama cannot be reached

Check:

```bash
ollama --version
ollama list
```

Then verify that the configured Ollama URL matches the running service, usually:

```text
http://127.0.0.1:11434
```

### OpenRouter returns `401 Unauthorized`

Check that the OpenRouter API key is present in `~/.meal-organizer/.env`, that the key is current and that the model identifier is valid for OpenRouter.

Run:

```bash
meal-organizer setup
meal-organizer doctor
```

### The plan exceeds the budget

The planner is intended to prioritize the weekly budget. If the calculated basket still exceeds the budget, do not accept the plan. Review the generated meals, replace expensive meals or regenerate the plan with a lower-cost configuration.

### A product is unexpectedly listed for purchase

Check the inventory:

```bash
meal-organizer inventory list
```

Make sure the ingredient exists in inventory and has a positive quantity. For measurable ingredients, use a compatible unit such as `g`, `ml` or `unit`.

## Development

Install the package in editable mode:

```bash
python -m pip install -e .
```

The project keeps CLI presentation separate from the core planning, pricing, database and LLM services so that a future HTTP/web frontend can reuse the same domain logic.

The main local paths are under:

```text
src/meal_organizer/
```

When changing the CLI, validate the entry point before testing domain features:

```bash
meal-organizer --help
meal-organizer doctor
```

## Architecture overview

The intended flow is:

```text
Inventory + Preferences + Equipment + Budget
                    |
                    v
             LLM meal planning
                    |
                    v
            Weekly meal plan
                    |
                    v
          Shopping list calculation
                    |
                    v
              Price estimation
                    |
                    v
          User accepts / pauses
                    |
                    v
         Recipe generation on demand
                    |
                    v
              Cooking mode
```

The design principle is that the LLM proposes ideas while application code remains responsible for persistence, inventory calculations, validation and shopping-cost calculations.

## License and external data

Check the repository and source documentation for the current license and third-party data terms. External price data, especially Open Prices/Open Food Facts data, remain subject to their own licensing and attribution requirements.