# QA Bug Reports: Warung Sales & Profit Engine

## Summary of Bug Hunt
* Total Bugs Identified: 4
* Resolved: 4
* Outstanding: 0

---

## Bug Report: BUG-001
### Severity: High
### Affected Component: Client (POS Checkout & Cart Bar)

#### 1. Steps to Reproduce
1. In the Kasir view, add 2x items to the cart.
2. The sticky bottom Cart Bar appears displaying "2 Item - Rp ...".
3. Open checkout modal, enter cash, and click "Simpan Transaksi".
4. Transaction succeeds and receipt modal opens.
5. Close the receipt modal or click "Selesai / Transaksi Baru".
6. Observe the bottom Cart Bar.

#### 2. Expected Behavior
Cart bar is hidden immediately upon transaction completion because the cart has been emptied (`state.cart = {}`).

#### 3. Actual Behavior
The cart bar remained visible showing previous items and total amount. Clicking it opened checkout with an empty list.

#### 4. Remediation Applied
Added explicit `updateCartBar()` call immediately following `state.cart = {}` in `app.js:308` to guarantee clean state transition.

---

## Bug Report: BUG-002
### Severity: High
### Affected Component: Client (Catalog Deletion & State Sync)

#### 1. Steps to Reproduce
1. Add "Indomie Rebus" to cart in Kasir view.
2. Navigate to "Menu" tab.
3. Click "Hapus" on "Indomie Rebus" and confirm.
4. Navigate back to "Kasir" and open checkout.
5. Click "Simpan Transaksi".

#### 2. Expected Behavior
Deleted menu items should be automatically purged from the active cart, and the cart bar updated.

#### 3. Actual Behavior
Cart retained the deleted product ID. Checkout payload sent the deleted product ID, causing backend to fail with "Product not found".

#### 4. Remediation Applied
In `app.js`, updated both `deleteProduct()` and `loadProducts()` to automatically purge cart keys whose product IDs no longer exist in the catalog, then immediately recalculate `updateCartBar()`.

---

## Bug Report: BUG-003
### Severity: Medium
### Affected Component: Backend Domain Validation (Null Type Coercion)

#### 1. Steps to Reproduce
1. Send `POST /api/v1/products` with payload `{"name": "Bakso", "costPrice": null, "sellingPrice": 10000}`.
2. Observe server validation.

#### 2. Expected Behavior
Server responds with 400 Bad Request rejecting null cost price.

#### 3. Actual Behavior
In JavaScript, `null < 0` is false and `isNaN(null)` is false, allowing `null` to bypass non-negative validation and coerce to `0` or `NaN` during margin arithmetic.

#### 4. Remediation Applied
In `ProductUseCases.ts`, `ExpenseUseCases.ts`, and `TransactionUseCases.ts`, updated validation checks to explicitly verify `typeof value === 'number' && !isNaN(value) && value !== null`.

---

## Bug Report: BUG-004
### Severity: Low
### Affected Component: Client UI (Catalog Header)

#### 1. Steps to Reproduce
1. Inspect the "Tambah Menu" section in the Catalog screen.
2. Observe button label and icon layout.

#### 2. Expected Behavior
A single, clean button with an SVG icon and clear text.

#### 3. Actual Behavior
Double plus icon was present (`+` in text and `+` in SVG).

#### 4. Remediation Applied
Cleaned up the DOM element to a single SVG plus icon and standardized text button.
