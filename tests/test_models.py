from meal_organizer.models import MealIngredient, MealPlan, PlannedMeal


def test_meal_plan_accepts_two_meals_per_day_shape():
    meals = [
        PlannedMeal(
            day=day,
            meal=meal,
            name=f"{day} {meal}",
            description="Test meal",
            ingredients=[MealIngredient(name="rice", quantity=100, unit="g")],
        )
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for meal in ["lunch", "dinner"]
    ]
    plan = MealPlan(meals=meals)
    assert len(plan.meals) == 14
