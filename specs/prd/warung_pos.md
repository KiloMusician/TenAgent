# PRD: Warung Sales and Profit Tracker

## 1. Executive Summary & Problem Statement
* Problem: Small food stall and grocery stall (warung) owners frequently track sales on paper or in memory, making it hard to track actual unit margins, daily sales volume, operational overheads, and real net profits.
* Solution: A standalone Android-first mobile application backed by a cloud database that manages menu catalog pricing (cost price vs selling price), records sales orders, logs daily operational expenses, and visualizes gross and net profit trends via interactive charts.
* Target Persona: Warung owners and staff who manage daily inventory pricing, register walk-in transactions, and need accurate profit metrics on their Android smartphones.

## 2. Scope & Boundaries
* In Scope (MVP):
  - Product Catalog Management: Add, edit, and view items with Product Name, Category, Cost Price (Modal Beli per unit), and Selling Price (Harga Jual).
  - Point of Sale / Order Entry: Fast product selection, quantity input, order line calculations, and instant transaction recording.
  - Expense Tracker: Record daily operational expenses (electricity, stall rent, plastic bags, ice, gas, etc.) with date, amount, category, and notes.
  - Profit Engine:
    - Gross Profit calculation: Total Revenue minus Total Cost of Goods Sold (COGS).
    - Net Profit calculation: Gross Profit minus Total Operational Expenses.
  - Sales & Profit Analytics: Interactive visual charts for daily, weekly, and monthly revenue, gross profit, and net profit.
  - Cloud Database Synchronization: Secure cloud persistence enabling real-time multi-device synchronization and backup.
* Out of Scope (Future Phases):
  - Thermal Bluetooth receipt printer integration (Phase 2).
  - Supplier purchase order and raw material batch tracking (Phase 2).
  - Multi-outlet branch management (Phase 2).
  - Customer loyalty point system (Phase 2).

## 3. User Stories & Acceptance Criteria

### US-001: Manage Products with Cost Price and Selling Price
* **As a**: Warung Owner
* **I want to**: Register menu items with their unit cost price (modal beli) and selling price (harga jual)
* **So that**: The application can accurately calculate profit margin per product and total profit.

#### Acceptance Criteria (Gherkin style)
* **Scenario 1**: Successful product creation
  - **Given**: The user is on the Add Product screen
  - **When**: The user enters product name "Es Teh Manis", cost price "1500", and selling price "4000", then submits
  - **Then**: The product is saved to the catalog and shows unit margin "Rp 2.500" (62.5% margin).
* **Scenario 2**: Validation error on invalid pricing
  - **Given**: The user is entering product pricing
  - **When**: The user enters a selling price lower than or equal to zero, or leaves cost price blank
  - **Then**: The system shows a validation error and prevents saving.

### US-002: Record Sales Transactions
* **As a**: Warung Cashier
* **I want to**: Select items from the catalog, specify quantities, and record sales
* **So that**: Daily customer purchases are stored and sales revenue is calculated automatically.

#### Acceptance Criteria (Gherkin style)
* **Scenario 1**: Recording a sale with multiple items
  - **Given**: Products exist in the catalog
  - **When**: The user adds 2x "Es Teh Manis" (Rp 4.000 each) and 1x "Nasi Goreng" (Rp 15.000, cost Rp 9.000) and completes checkout
  - **Then**: A transaction record is created with Total Revenue Rp 23.000, Total COGS Rp 12.000, and Gross Profit Rp 11.000.
* **Scenario 2**: Empty cart checkout prevention
  - **Given**: No items are selected in the checkout cart
  - **When**: The user taps complete sale
  - **Then**: The system disables the submit action and warns the user to select at least one item.

### US-003: Log Operational Expenses
* **As a**: Warung Owner
* **I want to**: Log operational expenses with date, amount, category, and description
* **So that**: Overhead costs are deducted from gross profit to get net profit.

#### Acceptance Criteria (Gherkin style)
* **Scenario 1**: Adding an operational expense
  - **Given**: The user is on the Expense screen
  - **When**: The user enters date "Today", amount "20000", category "Packaging", and notes "Plastik & sedotan"
  - **Then**: The expense is saved and deducted from the current period net profit calculation.
* **Scenario 2**: Zero or negative expense rejection
  - **Given**: The user inputs an expense amount of "0" or negative
  - **When**: The user taps save
  - **Then**: The form highlights the error and requires a positive value.

### US-004: View Sales & Profit Analytics Charts
* **As a**: Warung Owner
* **I want to**: View charts comparing revenue, gross profit, and net profit over time
* **So that**: I can assess business profitability and make informed purchasing decisions.

#### Acceptance Criteria (Gherkin style)
* **Scenario 1**: Displaying metrics and period filters
  - **Given**: The user navigates to the Analytics screen
  - **When**: The user selects filter "Last 7 Days"
  - **Then**: The screen displays summary cards for Total Revenue, Gross Profit, and Net Profit, alongside a bar/line chart plotting daily trends.
* **Scenario 2**: Handling period with no transactions
  - **Given**: A selected date range has no recorded sales or expenses
  - **When**: The analytics view loads
  - **Then**: The chart displays clean zero-baseline indicators with an honest empty state prompt to record sales.

## 4. Non-Functional Requirements
* Performance: Product catalog search and cart calculations must respond in under 100ms.
* Offline Support & Sync: The mobile client must allow recording transactions with local caching and sync to the cloud database when online.
* Reliability & Data Integrity: Financial calculations must use integer/fixed-precision arithmetic to avoid floating-point rounding errors.
* Security: API authentication using JWT with encrypted database connections (SSL/TLS).
