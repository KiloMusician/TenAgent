# ADR-001: Technology Stack and Clean Architecture Layers

## Status
Accepted

## Context
The user requested a dedicated mobile application for Android to manage a warung (stall/eatery) business. The system requires product catalog management with unit cost price and selling price, POS order entry, operational expense tracking, profit margin calculations (gross and net profit), and visual trend analytics. Data must be synchronized with a reliable cloud database.

## Decision
1. **Client Tier**: React Native with TypeScript (Expo framework).
   - Target: Android standalone APK.
   - UI Architecture: Clean Architecture pattern separating UI Screens and ViewModels from Domain entities and Data repositories.
   - Visualization: Native SVG-based charting (`react-native-chart-kit` / `react-native-svg`) for revenue and profit trend graphs.
2. **Backend API Tier**: Node.js with TypeScript and Express.
   - Architectural Pattern: 3-Layer Clean Architecture:
     - `domain/`: Business entities (Product, Transaction, Expense, ProfitSummary), value objects, and repository interfaces. No database or framework dependencies.
     - `data/`: PostgreSQL database connection, repository implementations, and data mappers.
     - `presentation/`: REST API controllers, input validation middleware, and route definitions conforming strictly to OpenAPI contract.
3. **Database Tier**: PostgreSQL.
   - Relational 3NF design with foreign key constraints, currency stored in integer cents/rupiah (`BIGINT` or `NUMERIC(15,2)`) to eliminate floating-point rounding errors.
   - Cloud hosted with connection pooling.

## Rationale & Alternatives Considered
* **Client**:
  * Option A (Chosen - React Native / Expo): Provides immediate Android standalone APK build capability, TypeScript end-to-end type sharing with backend, rich charting libraries, and high maintainability.
  * Option B (Rejected - Flutter): Excellent native performance, but introduces a dual-language Dart/TypeScript barrier between client and backend.
  * Option C (Rejected - Mobile Web only): Lacks direct native Android feel and APK distribution preference selected by the client.
* **Backend**:
  * Option A (Chosen - Node.js + TypeScript): Enables unified TypeScript models across client and server, rapid use case implementation, and lightweight memory footprint.
  * Option B (Rejected - Go): High performance, but slower development velocity for initial MVP modeling without cross-tier shared TypeScript types.
* **Database**:
  * Option A (Chosen - PostgreSQL): ACID-compliant transactional consistency essential for financial calculations, order lines, and ledger aggregation.
  * Option B (Rejected - MongoDB): Weak schema enforcement for multi-table financial aggregates (products, transactions, items, operational expenses).

## Consequences & Trade-offs
* Positive:
  - Strong compile-time safety and type alignment across API, client, and database models.
  - Decoupled domain business logic allows testing profit formulas independently of UI or database.
  - Scalable database schema ready for multi-device sync.
* Negative & Mitigations:
  - Mobile chart rendering requires careful layout constraint handling on small Android screens. Addressed via responsive container dimensions and accessibility tap targets.
