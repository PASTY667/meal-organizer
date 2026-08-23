# Meal Organizer

A local-first Python CLI for planning affordable, balanced meals from what you already have.

## Current status

The repository currently contains the first working foundation: a Rich/Typer CLI, local SQLite inventory, interactive setup, LLM provider abstraction for Ollama and OpenRouter, and an external price-estimation adapter for Open Prices.

The application is intentionally local-first. User configuration and inventory live under `~/.meal-organizer/`. API keys are never committed to the repository.

## Install

With Python 3.11+:

```bash
python -m pip install -e .
meal-organizer setup
```

For development:

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

## Main commands

```text
meal-organizer setup
meal-organizer doctor
meal-organizer inventory list
meal-organizer inventory add "rice" 500 --unit g --location cupboard
meal-organizer inventory remove "rice"
meal-organizer price "eggs"
meal-organizer plan
meal-organizer cook "chicken curry"
```

## LLM providers

Ollama is the default provider and expects a local Ollama server. OpenRouter can be selected during `setup` and requires an API key and model name.

The application keeps providers behind a small interface so the planning domain does not depend on a specific model vendor.

## Pricing

Open Prices is the intended primary external source for price observations. The adapter records source, confidence, observation date and sample count. Price data is an estimate, not a guarantee of the price in a particular shop.

Open Prices data is provided by Open Food Facts and is subject to its applicable open-data licence and attribution requirements.

## Design principles

The LLM proposes; application code validates. Allergies and other hard constraints must never be delegated exclusively to a model. Budget calculations and inventory state remain deterministic application data.

The CLI is separated from domain services so a future HTTP/web interface can reuse the same core.
