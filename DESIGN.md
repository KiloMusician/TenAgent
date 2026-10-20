# Design Direction: WARUNG BAROKAH - POS & Pelacak Laba

## 1. Brand Identity & Personality
* Product: WARUNG BAROKAH (Mobile Android & Web POS)
* Mood: Warm, energetic, high-legibility, utilitarian (Warung Makan & Toko Sembako)
* Target Persona: Warung owners operating quickly in bright indoor/outdoor shop environments
* Reading: Mobile POS and financial analytics for micro-merchants, in a high-contrast fresh green utilitarian style, dial ENERGY 2 / RHYTHM 2 / MOTION 1.

## 2. Dials
* ENERGY: 2 (Fresh balanced green, high visual clarity for rapid order entry and legible numbers)
* RHYTHM: 2 (Consistent item list cards with structured metric summaries)
* MOTION: 1 (Instant responsive feedback, zero decorative delay)

## 3. Design Tokens

### Primary Palette (Green Theme)
* Background: `#F8FAF8` (Clean Organic Ivory-Green - comfortable for long hours) / Dark: `#0F172A`
* Surface Card: `#FFFFFF` (White) / Dark Surface: `#1E293B`
* Text Primary: `#0F172A` (Slate 900 - contrast ratio 17.85:1 against white)
* Text Secondary: `#475569` (Slate 600 - contrast ratio 7.58:1 against white)
* Brand Primary / Accent: `#15803D` (Forest Green - WCAG AA ratio 4.54:1 on white, fresh merchant grocery vibe) / Dark: `#4ADE80` (Green 400 - contrast ratio 7.83:1 on dark surface)
* Brand Primary Hover: `#166534` (Deep Forest Green - WCAG AAA ratio 7.19:1 on white) / Dark: `#22C55E`
* Brand Primary Subtle: `#F0FDF4` (Green 50 - soft fresh tint) / Dark: `rgba(74, 222, 128, 0.15)`
* Brand Primary Border: `#BBF7D0` (Green 200 - border and dividers) / Dark: `#24362E`
* Revenue Metric: `#0284C7` (Sky Blue)
* Gross Profit Metric: `#0D9488` (Teal 600) / Dark: `#2DD4BF`
* Net Profit Metric: `#15803D` (Forest Green) / Dark: `#4ADE80`
* Customer Traffic Metric: `#15803D` (Forest Green) / Dark: `#4ADE80`
* Expense / Destructive: `#DC2626` (Red 600)
* Border / Divider: `#E2E8F0` (Clean Slate Stone)

### Typography Scale
* Font Family: System sans-serif (Android Roboto / Plus Jakarta Sans)
* Display Number: 28px / Bold (Metric cards)
* Screen Title: 20px / SemiBold (Top bar)
* Item Title: 16px / SemiBold (Product name)
* Body / Inputs: 14px / Regular (Form fields & lists)
* Caption / Margin: 12px / Medium (Profit margin percentage)

### Customer Traffic Chart Specification
* Canvas: `#customers-chart` (360x180 DPR-scaled)
* Bars: Discrete daily transaction frequency bars in `#15803D` (Dark: `#4ADE80`) with exact customer numbers positioned above each bar.
* Zero-Traffic Days: Subtle baseline indicator with muted gray counter (`0`) maintaining temporal consistency.
* Header Badge: `#metric-total-customers` (`badge-orange-traffic`, `#DCFCE7` / `#15803D`, Dark: `rgba(74, 222, 128, 0.2)` / `#4ADE80`) displaying total customers for active period.

### Digital Thermal Receipt Specification
* Header: **WARUNG BAROKAH**
* Type: Thermal Paper 58mm / 80mm monospaced simulation
* Background: Clean white `#FFFFFF` with dashed separator lines
* Elements: Warung Header, Tanggal & Jam, Invoice No, Item Name x Qty x Subtotal, Total Tagihan, Tunai, Kembalian, dan Pesan Terima Kasih.
* Actions:
  - "Cetak / Print Nota": Triggers standard browser/system print dialog with dedicated print media stylesheet (`@media print`).
  - "Bagikan ke WhatsApp": Generates direct WhatsApp shareable text receipt with formatted bill summary.

### Spacing & Touch Targets
* Base Spacing Grid: 4px, 8px, 12px, 16px, 24px, 32px
* Minimum Touch Target: 48px height for all buttons and interactive list rows
* Border Radius: 8px (Cards & inputs), 6px (Badges & secondary buttons)
* Elevation / Shadow: Low elevation (0 1px 3px rgba(21, 128, 61, 0.06))

## 4. Antislop Design Rationale (R-31)
* Why Forest Green `#15803D` & Dark Green `#4ADE80`? Evokes fresh grocery produce, trust, growth, and Indonesian micro-merchant vibrancy while satisfying WCAG AA accessibility contrast (> 4.5:1 on light, > 7.8:1 on dark).
* Why monospaced thermal receipt? Replicates physical POS receipts familiar to Indonesian customers and prints directly to Bluetooth/USB thermal printers or PDF.

## 5. Micro-Interactions & Animation Specification
* Physics Curve: Modern snappy spring curve `cubic-bezier(0.16, 1, 0.3, 1)`.
* Durations:
  - Micro-taps / Buttons / Chips: `0.15s` (`scale(0.92 - 0.96)` tactile press feedback).
  - Popups / Modal sheets: `0.22s - 0.24s` (`scale(0.96) -> 1` and `translateY(16px) -> 0` spring pop).
  - Screen views: `0.22s` (crisp 8px upward slide + opacity fade).
  - Toast notification: `0.22s` (`translateY(-20px) -> 0` slide down from top).
  - Floating Cart Bar: `0.24s` (`translateY(100%) -> 0` slide up from viewport bottom).
* Performance: 100% GPU-accelerated compositing using exclusively `transform` and `opacity`. Zero layout thrashing or CPU reflow.
* Accessibility: Fully respects `prefers-reduced-motion: reduce` by dampening animations to 0.01ms.
* Floating Cart Bar Overlay:
  - Detached from scrollable `.app-body` and mounted at mobile frame root with `z-index: 30`, floating steadily above bottom navigation (`bottom: 74px`).
  - Scroll Clearance: `#screen-pos` configured with `padding-bottom: 74px` (total `170px` scroll clearance), ensuring the lowest catalog cards scroll completely above the checkout bar without visual obstruction.

## 6. Payment Accordion & QRIS Specification
* Accordion Slider Interaction:
  - Cash and QRIS options feature tactile chevron indicators (`▼`) that smoothly rotate 180° upon activation.
  - Smooth vertical slide-down drawer transition (`max-height 0.28s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.22s`).
* QRIS Auto-Konek:
  - Displays official national red-and-white QRIS badge with merchant name and exact total amount.
  - Built-in photo uploader enables merchants to attach their custom QRIS image (stored persistently in client `localStorage` under `warung_custom_qris`).
  - Automatic connection upon opening checkout modal, with seamless fallback to crisp standard vector QRIS.


