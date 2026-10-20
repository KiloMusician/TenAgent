# Screen Specifications & User Flows: Warung POS & Profit Tracker

## 1. Global Navigation (Mobile Android)
* Bottom Navigation Bar (Height: 64px, touch target 48x48px per tab):
  1. **Kasir (POS)**: Icon shopping-cart, active color Emerald `#047857`.
  2. **Menu Produk**: Icon clipboard-list, active color Emerald `#047857`.
  3. **Biaya**: Icon wallet / receipt, active color Emerald `#047857`.
  4. **Laporan & Grafik**: Icon bar-chart-2, active color Emerald `#047857`.

---

## 2. Screen Specifications

### Screen 1: Point of Sale (Kasir)
* **User Goal**: Rapidly select items, review order total, and complete a cash sale.
* **Layout**:
  - Top Bar (56px): Search input for products + category filter chips.
  - Product Grid / List: 2-column touch cards with item name, selling price, and "+ Tambah" button.
  - Bottom Pinned Cart Bar (64px): Shows total items count, total price in Rupiah, and "Bayar Sekarang" action button.
* **Checkout Dialog**:
  - Modal displaying selected items, item quantities, total bill, cash received input, and calculated change.
  - Primary Action: "Simpan Transaksi" (48px height, Emerald background).
* **Empty State**:
  - Icon + Text: "Belum ada produk di menu. Buka tab Menu Produk untuk menambahkan barang dagangan."
* **Loading State**:
  - Pulse shimmer skeleton for product cards.

### Screen 2: Menu & Katalog Produk (Product Catalog)
* **User Goal**: Register and manage items, setting Modal Beli (Cost Price) and Harga Jual (Selling Price).
* **Layout**:
  - Header: Search input + Top Right CTA "+ Tambah Produk".
  - Product Item Card:
    - Row 1: Product Name (Bold 16px) + Category tag.
    - Row 2: Harga Jual (Rp 15.000) vs Modal Beli (Rp 10.000).
    - Row 3: Unit Profit Pill: `Margin: Rp 5.000 (33.3%)` in soft green badge.
    - Actions: Edit icon, Delete icon (with confirm alert).
* **Add / Edit Product Modal**:
  - Input: Nama Produk (string, required).
  - Input: Kategori (dropdown / chips: Makanan, Minuman, Sembako, Lainnya).
  - Input: Modal Beli Satuan (numeric, formatted with Rp currency mask).
  - Input: Harga Jual Satuan (numeric, formatted with Rp currency mask).
  - Real-time indicator: Displays calculated Unit Margin: `Laba per unit: Rp X (Y%)` while typing.
  - Buttons: "Batal" (Ghost) and "Simpan Produk" (Emerald Solid, 48px).

### Screen 3: Biaya Operasional (Expenses)
* **User Goal**: Record non-COGS overhead costs (listrik, air, sewa, kresek, gas) to calculate net profit.
* **Layout**:
  - Summary Header: "Total Pengeluaran Bulan Ini: Rp 450.000".
  - Quick Action: "+ Catat Pengeluaran".
  - Expense List: Date-grouped list rows with Category badge, description note, and negative currency formatting (`-Rp 25.000`).
* **Add Expense Modal**:
  - Input: Tanggal (defaults to today).
  - Input: Nominal Pengeluaran (numeric).
  - Input: Kategori (Listrik & Air, Sewa Tempat, Kantong & Kemasan, Gaji, Operasional Lain).
  - Input: Catatan / Keterangan (optional string).
  - Submit: "Simpan Pengeluaran".

### Screen 4: Laporan & Grafik Profit (Analytics Dashboard)
* **User Goal**: Review daily/weekly/monthly revenue, gross profit, and net profit with visual charts.
* **Layout**:
  - Period Filter Tabs: [Hari Ini | 7 Hari Terakhir | Bulan Ini].
  - 4 Key Metric Cards (2x2 Grid):
    1. **Total Penjualan (Omzet)**: Blue indicator, total gross sales.
    2. **Total Modal Terjual (COGS)**: Neutral gray indicator, total base cost of sold items.
    3. **Laba Kotor (Gross Profit)**: Emerald green indicator (`Omzet - Modal Terjual`).
    4. **Laba Bersih (Net Profit)**: Deep emerald or highlighted border (`Laba Kotor - Biaya Operasional`).
  - Interactive Chart Section:
    - Type: Stacked / Dual Bar Chart or Multi-Line Chart.
    - Series 1 (Green): Omzet / Penjualan.
    - Series 2 (Teal): Laba Kotor.
    - Series 3 (Blue): Laba Bersih.
    - X-Axis: Dates / Days.
    - Y-Axis: Rupiah (Rp in thousands/millions).
  - Expense Breakdown:
    - Donut chart or list showing top expense categories for the selected period.

## 3. Accessibility & Usability Assurance
- All buttons have minimum dimensions of 48px height and 48px touch bounding box.
- Text contrast ratio exceeds 4.5:1 against light card backgrounds.
- High-contrast visual cues for negative/profit numbers.
- Number formatting adheres to standard Indonesian Rupiah style (`Rp 10.000`).
