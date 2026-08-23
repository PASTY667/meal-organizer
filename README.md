# Meal Organizer

Meal Organizer is a local-first Python CLI for planning affordable, balanced meals from what you already have, while building a realistic weekly shopping list.

## Install

With Python 3.11+:

```bash
python -m pip install -e .
meal-organizer setup
```

The setup wizard stores the complete configuration in `~/.meal-organizer/.env`. API keys are never committed to the repository.

## Setup

The wizard lets you choose French or English. The selected language controls CLI prompts, generated meal plans, questions and recipes.

For the LLM you can choose Ollama for a local model or OpenRouter for a hosted model. When OpenRouter is selected, web search can be enabled for recipe research.

## Main workflow

```text
meal-organizer setup
meal-organizer inventory add "riz" 500 --unit g --location cupboard
meal-organizer inventory add "oeufs" 6 --unit unit --location fridge
meal-organizer plan
```

`plan` creates exactly two meals per day, lunch and dinner. It uses the current inventory as a starting point but is not limited to it. The generated plan is persisted locally and the CLI shows a separate shopping list calculated from the ingredients required by the whole week.

The planning session is interactive: accept it, pause it, ask a question about a meal, or replace a meal. A paused plan can be resumed with:

```bash
meal-organizer plan --resume
```

Once a plan is accepted, recipes are generated on demand:

```bash
meal-organizer recipe Monday
meal-organizer cook Monday
```

The recipe generator receives the planned meal, current inventory and shopping list. With OpenRouter web search enabled it can research current recipes and return sources.

## Pricing

Open Prices is the primary external price source. Meal Organizer calculates ingredient costs using requested quantities and, when available, product package sizes. The shopping list uses estimated purchase cost rather than pretending that an ingredient already in inventory costs zero.

Prices remain estimates and are not guarantees for a particular shop. Open Prices is maintained by Open Food Facts and its data is subject to the applicable OdBL licence and attribution requirements.

## Design principles

The LLM proposes; application code validates and calculates. Allergies, inventory state, quantities and budget remain application data. Full recipes are not stored inside the weekly plan: the plan stores meal descriptions and ingredients, while recipes are generated and persisted separately when requested.

Meal plans and recipes are stored in SQLite under `~/.meal-organizer/`, so a generation can be paused and resumed without keeping the terminal session open.

The CLI is separated from domain services so a future HTTP/web interface can reuse the same core.
