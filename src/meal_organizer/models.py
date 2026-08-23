from pydantic import BaseModel, Field


class MealIngredient(BaseModel):
    name: str
    quantity: float = Field(ge=0)
    unit: str
    from_inventory: bool = False


class PlannedMeal(BaseModel):
    day: str
    meal: str
    recipe: str
    ingredients: list[MealIngredient]
    estimated_cost: float = Field(ge=0)


class MealPlan(BaseModel):
    meals: list[PlannedMeal]
    total_estimated_cost: float = Field(ge=0)
    notes: list[str] = []
