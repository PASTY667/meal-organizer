# Meal Organizer

A local-first Python CLI for planning affordable, balanced meals from what you already have.

## Current status

The repository currently contains the first working foundation: a Rich/Typer CLI, local SQLite inventory, interactive setup, LLM provider abstraction for Ollama and OpenRouter, and an external price-estimation adapter for Open Prices.

The application is local-first. User settings live in `~/.meal-organizer/.env` and inventory lives in `~/.meal-organizer/`. The `.env` file is ignored by Git and should never be committed because it may contain an OpenRouter API key.

## Install

With Python 3.11+:

```bash
python -m pip install -e .
meal-organizer setup
```

`setup` creates or updates `~/.meal-organizer/.env` and guides you through the LLM configuration. You can choose between a local Ollama model and OpenRouter. When Ollama is selected, the setup checks the local Ollama server and shows installed models when available. When OpenRouter is selected, it asks for the model and API key without echoing the key.

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

## Configuration

The generated configuration uses environment variables in `~/.meal-organizer/.env`. A template is available at `.env.example`.

For Ollama:

```text
MEAL_ORGANIZER_LLM_PROVIDER=ollama
MEAL_ORGANIZER_OLLAMA_MODEL="qwen3:8b"
MEAL_ORGANIZER_OLLAMA_HOST="http://127.0.0.1:11434"
```

For OpenRouter:

```text
MEAL_ORGANIZER_LLM_PROVIDER=openrouter
MEAL_ORGANIZER_OPENROUTER_MODEL="your/provider-model"
MEAL_ORGANIZER_OPENROUTER_API_KEY="your-secret-key"
```

Environment variables beginning with `MEAL_ORGANIZER_` override values from the `.env` file, which makes CI and deployment configuration possible without editing the file.

## LLM providers

Ollama is the default provider and expects a local Ollama server. OpenRouter can be selected during `setup` and requires an API key and model name.

The application keeps providers behind a small interface so the planning domain does not depend on a specific model vendor.

## Pricing

Open Prices is the intended primary external source for price observations. The adapter records source, confidence, observation date and sample count. Price data is an estimate, not a guarantee of the price in a particular shop.

Open Prices data is provided by Open Food Facts and is subject to its applicable open-data licence and attribution requirements.

## Design principles

The LLM proposes; application code validates. Allergies and other hard constraints must never be delegated exclusively to a model. Budget calculations and inventory state remain deterministic application data.

The CLI is separated from domain services so a future HTTP/web interface can reuse the same core.
