# Budget priority

The weekly shopping budget is a hard constraint during plan generation. The planner may sacrifice novelty, premium ingredients, or recipe complexity to stay within budget, but it must keep allergies, dislikes, equipment and meal completeness as hard constraints.

Generation uses deterministic purchase-cost calculation after each candidate plan and feeds the over-budget amount back to the LLM. The candidate is accepted only when its estimated shopping basket is within the configured budget.
