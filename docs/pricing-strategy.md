# Pricing strategy

Meal Organizer treats prices as purchase estimates, not LLM-generated facts.

The priority order is: 1) retailer observations when available, 2) validated Open Prices observations, 3) French supermarket reference packages. An observation is rejected when its unit price is an outlier for the product reference.

The planner must satisfy the weekly shopping budget before optimizing variety. Variety remains a secondary objective.

Direct retailer scraping is intentionally not enabled by default. E.Leclerc and Intermarché catalogues are dynamic and can change structure or availability by store. The pricing service therefore exposes retailer-aware references while keeping the core estimator deterministic. A future retailer adapter can use an official/catalogue endpoint without coupling the planner to HTML scraping.
