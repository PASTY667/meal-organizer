from pydantic import BaseModel, Field


class MealIngredient(BaseModel):
    name: str
    quantity: float = Field(gt=0)
    unit: str
    from_inventory: bool = False
    estimated_cost: float | None = Field(default=None, ge=0)


class PlannedMeal(BaseModel):
    day: str
    meal: str
    name: str
    description: str
    ingredients: list[MealIngredient]
    estimated_cost: float | None = Field(default=None, ge=0)
    web_researched: bool = False


class MealPlan(BaseModel):
    meals: list[PlannedMeal]
    shopping_cost: float = Field(default=0, ge=0)
    total_food_cost: float = Field(default=0, ge=0)
    notes: list[str] = Field(default_factory=list)


class RecipeIngredient(BaseModel):
    name: str
    quantity: float = Field(gt=0)
    unit: str


class Recipe(BaseModel):
    name: str
    description: str
    servings: int = Field(ge=1)
    ingredients: list[RecipeIngredient]
    steps: list[str] = Field(min_length=1)
    preparation_minutes: int = Field(ge=0)
    cooking_minutes: int = Field(ge=0)
    tips: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
