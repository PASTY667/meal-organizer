from meal_organizer.db import Database
from meal_organizer.models import MealIngredient, MealPlan, PlannedMeal, Recipe


def test_inventory_roundtrip(tmp_path):
    db = Database(tmp_path / "test.db")
    db.upsert_inventory("rice", 500, "g", "cupboard")
    db.upsert_inventory("eggs", 6, "unit", "fridge")

    items = db.list_inventory()
    assert [item.name for item in items] == ["eggs", "rice"]
    assert items[1].quantity == 500

    assert db.remove_inventory("eggs") is True
    assert db.remove_inventory("missing") is False


def test_plan_and_recipe_are_persisted(tmp_path):
    db = Database(tmp_path / "meal.db")
    plan = MealPlan(
        meals=[
            PlannedMeal(
                day="Monday",
                meal="lunch",
                name="Rice bowl",
                description="Simple bowl",
                ingredients=[MealIngredient(name="rice", quantity=100, unit="g")],
            )
        ]
    )
    plan_id = db.save_plan(plan, "paused")
    loaded = db.load_latest_plan()
    assert loaded is not None
    assert loaded[0] == plan_id
    assert loaded[2].meals[0].name == "Rice bowl"

    recipe = Recipe(
        name="Rice bowl",
        description="Simple",
        servings=1,
        ingredients=[],
        steps=["Cook the rice."],
        preparation_minutes=2,
        cooking_minutes=10,
    )
    db.save_recipe(plan_id, "Monday", recipe)
    assert db.load_recipe(plan_id, "Monday").name == "Rice bowl"
