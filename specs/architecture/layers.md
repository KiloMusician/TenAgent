# Architectural Layers & Boundary Specifications

## 1. Clean Architecture Overview
The system is divided into three distinct layers with strict inward-pointing dependencies.

```
┌────────────────────────────────────────────────────────┐
│                   PRESENTATION LAYER                   │
│   (Express Controllers, Validation, React Native UI)   │
└───────────────────────────┬────────────────────────────┘
                            │ depends on
┌───────────────────────────▼────────────────────────────┐
│                      DOMAIN LAYER                      │
│     (Entities, Value Objects, Use Cases, Repositories) │
│           * Pure business logic, zero external deps *   │
└───────────────────────────▲────────────────────────────┘
                            │ implemented by
┌───────────────────────────┴────────────────────────────┐
│                       DATA LAYER                       │
│      (PostgreSQL Pool, SQL Repositories, Migrations)   │
└────────────────────────────────────────────────────────┘
```

## 2. Layer Definitions

### 2.1 Domain Layer (`src/domain/`)
* **Entities**:
  - `Product`: `id`, `name`, `category`, `costPrice`, `sellingPrice`, `createdAt`, `updatedAt`
  - `Transaction`: `id`, `invoiceNumber`, `totalRevenue`, `totalCogs`, `grossProfit`, `createdAt`
  - `TransactionItem`: `id`, `transactionId`, `productId`, `productName`, `quantity`, `costPrice`, `sellingPrice`, `subtotalRevenue`, `subtotalCogs`
  - `Expense`: `id`, `date`, `amount`, `category`, `notes`, `createdAt`
  - `ProfitSummary`: `period`, `totalRevenue`, `totalCogs`, `grossProfit`, `totalExpenses`, `netProfit`, `marginPercent`
* **Interfaces**:
  - `IProductRepository`: CRUD operations for product inventory and pricing.
  - `ITransactionRepository`: Atomic transaction recording and historical queries.
  - `IExpenseRepository`: Record and query operational overheads.
  - `IAnalyticsRepository`: Aggregate daily/weekly/monthly profit summaries.

### 2.2 Data Layer (`src/data/`)
* Implements repository interfaces using `pg` (PostgreSQL client) with parameterized queries.
* Executes database transactions (`BEGIN`, `COMMIT`, `ROLLBACK`) during sale creation to ensure order header and items remain consistent.

### 2.3 Presentation Layer (`src/presentation/`)
* HTTP Controllers handling request validation, HTTP status codes, and JSON serialization.
* Mobile Client UI containing screens:
  - `ProductCatalogScreen`: Manage items, cost prices, selling prices, and unit margins.
  - `PointOfSaleScreen`: Cart selection, quantity adjustment, and checkout.
  - `ExpenseScreen`: Daily operational expense input and list.
  - `AnalyticsDashboardScreen`: Visual charts for Revenue, Gross Profit, and Net Profit.
