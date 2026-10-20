# Master Data Dictionary

> **Zero Duplication Registry**: All database tables and core entities across the system must be registered here. Before creating any new table or entity, the Database Engineer audits this registry to ensure no duplicate or overlapping data structures are introduced.

---

## Registered Tables

| Table Name | Entity Concept | Primary Key | Critical Foreign Keys | Owner Domain | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `products` | Product catalog with unit cost & selling price | `id` (UUID) | None | Catalog | Active |
| `transactions` | Point of sale checkout header records | `id` (UUID) | None | Sales | Active |
| `transaction_items` | Individual line items within a sales transaction | `id` (UUID) | `transaction_id -> transactions.id`, `product_id -> products.id` | Sales | Active |
| `expenses` | Daily operational overheads (rent, power, bags) | `id` (UUID) | None | Accounting | Active |

---

## Entity Relationship Guidelines
1. **Single Source of Truth (SSOT)**: 
   - `products` is the authoritative source for catalog pricing.
   - Historical item sales freeze their respective `cost_price` and `selling_price` inside `transaction_items` so future catalog price changes never corrupt past financial reports.
2. **Naming Conventions**: Table names are lowercase `snake_case` in plural form (`products`, `transactions`, `transaction_items`, `expenses`).
3. **Audit Trail**: Every mutable table requires `created_at` and `updated_at` timestamps with timezone.
4. **Numeric Precision**: Currency fields use `NUMERIC(15,2)` to prevent floating-point rounding discrepancies.
