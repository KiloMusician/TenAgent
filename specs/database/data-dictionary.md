# Master Data Dictionary

> **Zero Duplication Registry**: All database tables and core entities across the system must be registered here. Before creating any new table or entity, the Database Engineer audits this registry to ensure no duplicate or overlapping data structures are introduced.

---

## Registered Tables

| Table Name | Entity Concept | Primary Key | Critical Foreign Keys | Owner Domain | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| *(None yet)* | *(Awaiting Project Discovery)* | - | - | - | Initialized |

---

## Entity Relationship Guidelines
1. **Single Source of Truth (SSOT)**: If an entity already exists (e.g., `users`), all user-related data must link directly to this table rather than creating secondary identity stores.
2. **Naming Conventions**: Table names are lowercase `snake_case` in plural form (e.g., `orders`, `user_sessions`, `payment_intents`).
3. **Audit Trail**: Every mutable table requires `created_at` and `updated_at` timestamp with timezone.
