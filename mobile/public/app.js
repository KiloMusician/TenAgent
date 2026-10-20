// Warung POS & Profit Tracker Mobile Client Logic
const API_BASE = '/api/v1';

const state = {
  activeScreen: 'screen-pos',
  products: [],
  cart: {}, // productId -> quantity
  expenses: [],
  analyticsPeriod: 'today',
  selectedCategory: 'ALL',
  posSearch: '',
  catalogSearch: '',
  editingProductId: null,
  lastChartData: null
};

// Theme Mode Helper
function isDarkMode() {
  return document.documentElement.getAttribute('data-theme') === 'dark';
}

function initTheme() {
  const toggleBtn = document.getElementById('btn-theme-toggle');
  const iconMoon = document.getElementById('theme-icon-moon');
  const iconSun = document.getElementById('theme-icon-sun');

  function updateThemeUI(theme) {
    if (theme === 'dark') {
      if (iconMoon) iconMoon.classList.add('hidden');
      if (iconSun) iconSun.classList.remove('hidden');
      if (toggleBtn) toggleBtn.setAttribute('title', 'Beralih ke Tema Terang (Light Mode)');
    } else {
      if (iconSun) iconSun.classList.add('hidden');
      if (iconMoon) iconMoon.classList.remove('hidden');
      if (toggleBtn) toggleBtn.setAttribute('title', 'Beralih ke Tema Gelap (Dark Mode)');
    }
  }

  const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
  updateThemeUI(currentTheme);

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const active = document.documentElement.getAttribute('data-theme') || 'light';
      const newTheme = active === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', newTheme);
      try {
        localStorage.setItem('warung_theme', newTheme);
      } catch (e) {}
      updateThemeUI(newTheme);

      // Re-draw charts immediately if analytics data is present
      if (state.lastChartData && state.activeScreen === 'screen-analytics') {
        drawChart(state.lastChartData);
        drawCustomersChart(state.lastChartData);
      }
    });
  }
}

// Utilities
function formatRupiah(num) {
  const rounded = Math.round(num || 0);
  return 'Rp ' + rounded.toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

function showToast(message) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = message;
  toast.classList.remove('hidden');
  setTimeout(() => {
    toast.classList.add('hidden');
  }, 3000);
}

// Navigation Handler
function initNavigation() {
  const navButtons = document.querySelectorAll('.nav-item');
  const screens = document.querySelectorAll('.screen-view');
  const screenTitle = document.getElementById('screen-title');

  const titles = {
    'screen-pos': 'Kasir Penjualan',
    'screen-products': 'Katalog Menu & Modal',
    'screen-expenses': 'Biaya Operasional',
    'screen-analytics': 'Laporan & Grafik Profit'
  };

  navButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      navButtons.forEach(b => b.classList.remove('active'));
      screens.forEach(s => s.classList.remove('active'));

      btn.classList.add('active');
      const targetScreen = document.getElementById(targetId);
      if (targetScreen) targetScreen.classList.add('active');

      state.activeScreen = targetId;
      if (screenTitle && titles[targetId]) {
        screenTitle.textContent = titles[targetId];
      }

      updateCartBar();

      if (targetId === 'screen-analytics') {
        loadAnalytics();
      } else if (targetId === 'screen-expenses') {
        loadExpenses();
      } else if (targetId === 'screen-products') {
        loadProducts();
      } else if (targetId === 'screen-pos') {
        renderPosProducts();
      }
    });
  });

  const syncBtn = document.getElementById('btn-sync');
  if (syncBtn) {
    syncBtn.addEventListener('click', async () => {
      showToast('Menyinkronkan data...');
      await loadProducts();
      await loadExpenses();
      if (state.activeScreen === 'screen-analytics') {
        await loadAnalytics();
      }
      showToast('Data berhasil diperbarui');
    });
  }
}

// API Service Callers
async function fetchAPI(endpoint, options = {}) {
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Request failed' }));
      throw new Error(err.error || 'Terjadi kesalahan pada server');
    }
    if (res.status === 204) return true;
    return await res.json();
  } catch (error) {
    console.error(`API Error on ${endpoint}:`, error);
    showToast(error.message);
    throw error;
  }
}

// Products & POS Functions
async function loadProducts() {
  try {
    const data = await fetchAPI('/products');
    state.products = data;
    // Clean up cart for products that no longer exist
    Object.keys(state.cart).forEach(id => {
      if (!state.products.some(p => p.id === id)) {
        delete state.cart[id];
      }
    });
    updateCartBar();
    renderPosProducts();
    renderCatalogList();
  } catch {
    // Error handled in fetchAPI
  }
}

function renderPosProducts() {
  const container = document.getElementById('pos-products-container');
  if (!container) return;

  const filtered = state.products.filter(p => {
    if (state.selectedCategory !== 'ALL' && p.category.toLowerCase() !== state.selectedCategory.toLowerCase()) {
      return false;
    }
    if (state.posSearch && !p.name.toLowerCase().includes(state.posSearch.toLowerCase())) {
      return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="grid-column: span 2;">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/>
        </svg>
        <p>Tidak ada menu yang sesuai kriteria.</p>
        <button class="btn btn-primary btn-sm mt-2" onclick="openAddProductModal()">+ Tambah Menu Baru</button>
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map(item => {
    const qty = state.cart[item.id] || 0;
    return `
      <div class="pos-card" onclick="addToCart('${item.id}')">
        <div class="pos-card-header">
          <span class="item-category">${escapeHtml(item.category)}</span>
          <h3 class="item-title">${escapeHtml(item.name)}</h3>
        </div>
        <div class="pos-card-pricing">
          <div class="price-sell">${formatRupiah(item.sellingPrice)}</div>
          <div class="price-cost">Modal: ${formatRupiah(item.costPrice)}</div>
        </div>
        <div class="pos-card-actions">
          ${qty === 0 ? `
            <button class="btn-add-cart" onclick="event.stopPropagation(); addToCart('${item.id}')">
              <span>+ Tambah</span>
            </button>
          ` : `
            <div class="cart-stepper" onclick="event.stopPropagation()">
              <button onclick="decrementCart('${item.id}')">&minus;</button>
              <span class="count">${qty}</span>
              <button onclick="addToCart('${item.id}')">&plus;</button>
            </div>
          `}
        </div>
      </div>
    `;
  }).join('');

  updateCartBar();
}

function addToCart(productId) {
  state.cart[productId] = (state.cart[productId] || 0) + 1;
  renderPosProducts();
}

function decrementCart(productId) {
  if (!state.cart[productId]) return;
  state.cart[productId] -= 1;
  if (state.cart[productId] <= 0) {
    delete state.cart[productId];
  }
  renderPosProducts();
}

function updateCartBar() {
  const cartBar = document.getElementById('cart-bar');
  const countEl = document.getElementById('cart-item-count');
  const priceEl = document.getElementById('cart-total-price');

  let totalItems = 0;
  let totalPrice = 0;

  Object.entries(state.cart).forEach(([id, qty]) => {
    const product = state.products.find(p => p.id === id);
    if (product) {
      totalItems += qty;
      totalPrice += product.sellingPrice * qty;
    }
  });

  if (totalItems > 0 && state.activeScreen === 'screen-pos') {
    cartBar.classList.remove('hidden');
    countEl.textContent = `${totalItems} Item`;
    priceEl.textContent = formatRupiah(totalPrice);
  } else {
    cartBar.classList.add('hidden');
  }
}

// Checkout & Payment Handling (Cash & QRIS Accordion)
let currentCheckoutPaymentMethod = 'CASH';

function generateDefaultQrisSvg() {
  return `
    <svg viewBox="0 0 200 200" width="140" height="140" xmlns="http://www.w3.org/2000/svg" style="background:#FFFFFF; border-radius:4px;">
      <!-- Background -->
      <rect width="200" height="200" fill="#FFFFFF"/>
      
      <!-- Top-Left Finder Pattern -->
      <rect x="15" y="15" width="46" height="46" fill="#000000" rx="3"/>
      <rect x="21" y="21" width="34" height="34" fill="#FFFFFF" rx="2"/>
      <rect x="28" y="28" width="20" height="20" fill="#000000" rx="2"/>

      <!-- Top-Right Finder Pattern -->
      <rect x="139" y="15" width="46" height="46" fill="#000000" rx="3"/>
      <rect x="145" y="21" width="34" height="34" fill="#FFFFFF" rx="2"/>
      <rect x="152" y="28" width="20" height="20" fill="#000000" rx="2"/>

      <!-- Bottom-Left Finder Pattern -->
      <rect x="15" y="139" width="46" height="46" fill="#000000" rx="3"/>
      <rect x="21" y="145" width="34" height="34" fill="#FFFFFF" rx="2"/>
      <rect x="28" y="152" width="20" height="20" fill="#000000" rx="2"/>

      <!-- Bottom-Right Alignment Pattern -->
      <rect x="145" y="145" width="24" height="24" fill="#000000" rx="2"/>
      <rect x="150" y="150" width="14" height="14" fill="#FFFFFF"/>
      <rect x="154" y="154" width="6" height="6" fill="#000000"/>

      <!-- Timing Patterns -->
      <g fill="#000000">
        <rect x="68" y="34" width="7" height="7"/><rect x="82" y="34" width="7" height="7"/><rect x="96" y="34" width="7" height="7"/><rect x="110" y="34" width="7" height="7"/><rect x="124" y="34" width="7" height="7"/>
        <rect x="34" y="68" width="7" height="7"/><rect x="34" y="82" width="7" height="7"/><rect x="34" y="96" width="7" height="7"/><rect x="34" y="110" width="7" height="7"/><rect x="34" y="124" width="7" height="7"/>
      </g>

      <!-- Standard QR Data Modules -->
      <g fill="#000000">
        <rect x="68" y="18" width="6" height="6"/><rect x="80" y="18" width="6" height="6"/><rect x="98" y="18" width="6" height="6"/><rect x="116" y="18" width="6" height="6"/>
        <rect x="74" y="48" width="6" height="6"/><rect x="92" y="48" width="6" height="6"/><rect x="110" y="48" width="6" height="6"/><rect x="128" y="48" width="6" height="6"/>
        <rect x="18" y="68" width="6" height="6"/><rect x="48" y="74" width="6" height="6"/><rect x="68" y="68" width="6" height="6"/><rect x="80" y="68" width="6" height="6"/><rect x="122" y="68" width="6" height="6"/><rect x="140" y="68" width="6" height="6"/><rect x="158" y="68" width="6" height="6"/><rect x="176" y="68" width="6" height="6"/>
        <rect x="18" y="86" width="6" height="6"/><rect x="48" y="92" width="6" height="6"/><rect x="68" y="86" width="6" height="6"/><rect x="122" y="86" width="6" height="6"/><rect x="146" y="86" width="6" height="6"/><rect x="164" y="86" width="6" height="6"/>
        <rect x="18" y="104" width="6" height="6"/><rect x="48" y="110" width="6" height="6"/><rect x="68" y="104" width="6" height="6"/><rect x="122" y="104" width="6" height="6"/><rect x="152" y="104" width="6" height="6"/><rect x="170" y="104" width="6" height="6"/>
        <rect x="18" y="122" width="6" height="6"/><rect x="68" y="122" width="6" height="6"/><rect x="86" y="122" width="6" height="6"/><rect x="104" y="122" width="6" height="6"/><rect x="122" y="122" width="6" height="6"/><rect x="140" y="122" width="6" height="6"/><rect x="164" y="122" width="6" height="6"/>
        <rect x="68" y="140" width="6" height="6"/><rect x="86" y="140" width="6" height="6"/><rect x="110" y="140" width="6" height="6"/><rect x="128" y="140" width="6" height="6"/>
        <rect x="68" y="158" width="6" height="6"/><rect x="92" y="158" width="6" height="6"/><rect x="116" y="158" width="6" height="6"/><rect x="134" y="158" width="6" height="6"/>
        <rect x="68" y="176" width="6" height="6"/><rect x="80" y="176" width="6" height="6"/><rect x="98" y="176" width="6" height="6"/><rect x="116" y="176" width="6" height="6"/><rect x="176" y="176" width="6" height="6"/>
      </g>

      <!-- Central QRIS Badge -->
      <rect x="70" y="84" width="60" height="28" rx="5" fill="#FFFFFF" stroke="#DC2626" stroke-width="2"/>
      <rect x="73" y="87" width="54" height="22" rx="3" fill="#DC2626"/>
      <text x="100" y="103" font-family="'Plus Jakarta Sans', Arial, sans-serif" font-size="11" font-weight="900" fill="#FFFFFF" text-anchor="middle" letter-spacing="1">QRIS</text>
    </svg>
  `;
}

function renderQrisDisplay() {
  const container = document.getElementById('qris-code-container');
  const statusPill = document.getElementById('qris-status-pill');
  const btnReset = document.getElementById('btn-reset-qris');
  const nominalEl = document.getElementById('qris-nominal-display');

  const totalRevenue = getCartTotal();
  if (nominalEl) nominalEl.textContent = formatRupiah(totalRevenue);

  const customQris = localStorage.getItem('warung_custom_qris');
  if (customQris) {
    if (container) {
      container.innerHTML = `<img src="${customQris}" alt="QRIS Warung Barokah" class="qris-img-preview">`;
    }
    if (statusPill) {
      statusPill.textContent = '✓ Terhubung (Auto Konek)';
      statusPill.className = 'status-pill connected';
    }
    if (btnReset) btnReset.classList.remove('hidden');
  } else {
    if (container) {
      container.innerHTML = generateDefaultQrisSvg();
    }
    if (statusPill) {
      statusPill.textContent = 'QRIS Standar';
      statusPill.className = 'status-pill default';
    }
    if (btnReset) btnReset.classList.add('hidden');
  }
}

function initCheckoutModal() {
  const modal = document.getElementById('modal-checkout');
  const btnOpen = document.getElementById('btn-open-checkout');
  const btnClose = document.getElementById('btn-close-checkout');
  const btnCancel = document.getElementById('btn-cancel-checkout');
  const btnConfirm = document.getElementById('btn-confirm-checkout');
  const cashInput = document.getElementById('checkout-cash-received');

  const accordionCash = document.getElementById('accordion-cash');
  const accordionQris = document.getElementById('accordion-qris');
  const btnToggleCash = document.getElementById('btn-toggle-cash');
  const btnToggleQris = document.getElementById('btn-toggle-qris');

  const inputCustomQris = document.getElementById('input-custom-qris');
  const btnResetQris = document.getElementById('btn-reset-qris');

  btnOpen.addEventListener('click', () => {
    populateCheckoutModal();
    modal.classList.remove('hidden');
  });

  const closeModal = () => modal.classList.add('hidden');
  btnClose.addEventListener('click', closeModal);
  btnCancel.addEventListener('click', closeModal);

  // Accordion Drawer Toggle Handlers
  if (btnToggleCash) {
    btnToggleCash.addEventListener('click', () => {
      currentCheckoutPaymentMethod = 'CASH';
      if (accordionCash) accordionCash.classList.add('active');
      if (accordionQris) accordionQris.classList.remove('active');
      const badgeCash = accordionCash ? accordionCash.querySelector('.method-status-badge') : null;
      const badgeQris = accordionQris ? accordionQris.querySelector('.method-status-badge') : null;
      if (badgeCash) { badgeCash.textContent = 'Dipilih'; badgeCash.className = 'method-status-badge badge-cash'; }
      if (badgeQris) { badgeQris.textContent = 'Otomatis Pas'; badgeQris.className = 'method-status-badge badge-qris'; }
      if (btnConfirm) btnConfirm.textContent = 'Simpan Transaksi (Tunai)';
      calculateChange();
    });
  }

  if (btnToggleQris) {
    btnToggleQris.addEventListener('click', () => {
      currentCheckoutPaymentMethod = 'QRIS';
      if (accordionQris) accordionQris.classList.add('active');
      if (accordionCash) accordionCash.classList.remove('active');
      const badgeCash = accordionCash ? accordionCash.querySelector('.method-status-badge') : null;
      const badgeQris = accordionQris ? accordionQris.querySelector('.method-status-badge') : null;
      if (badgeQris) { badgeQris.textContent = 'Dipilih'; badgeQris.className = 'method-status-badge badge-qris'; }
      if (badgeCash) { badgeCash.textContent = 'Tunai'; badgeCash.className = 'method-status-badge badge-cash'; }
      if (btnConfirm) btnConfirm.textContent = 'Konfirmasi Pembayaran QRIS';
      renderQrisDisplay();
    });
  }

  // QRIS Custom Image Upload (Auto Konek via localStorage)
  if (inputCustomQris) {
    inputCustomQris.addEventListener('change', (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      if (!file.type.startsWith('image/')) {
        showToast('Pilih file gambar (JPG/PNG)');
        return;
      }

      if (file.size > 2.5 * 1024 * 1024) {
        showToast('Ukuran gambar maksimal 2.5MB');
        return;
      }

      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const base64Data = event.target.result;
          localStorage.setItem('warung_custom_qris', base64Data);
          renderQrisDisplay();
          showToast('Foto QRIS berhasil dipasang & auto konek!');
        } catch {
          showToast('Gagal menyimpan gambar, memori lokal penuh');
        }
      };
      reader.readAsDataURL(file);
    });
  }

  if (btnResetQris) {
    btnResetQris.addEventListener('click', () => {
      localStorage.removeItem('warung_custom_qris');
      renderQrisDisplay();
      showToast('QRIS di-reset ke standar Warung Barokah');
    });
  }

  cashInput.addEventListener('input', () => {
    // Clear active quick chip when typing manually
    document.querySelectorAll('.cash-chip').forEach(c => c.classList.remove('active'));
    calculateChange();
  });

  // Quick cash denomination chips
  const cashChips = document.querySelectorAll('.cash-chip');
  cashChips.forEach(chip => {
    chip.addEventListener('click', () => {
      cashChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');

      const val = chip.getAttribute('data-val');
      let totalRevenue = getCartTotal();

      if (val === 'exact') {
        cashInput.value = totalRevenue;
      } else {
        const nominal = parseInt(val, 10);
        cashInput.value = nominal;
      }
      calculateChange();
    });
  });

  btnConfirm.addEventListener('click', async () => {
    const items = Object.entries(state.cart).map(([productId, quantity]) => ({
      productId,
      quantity
    }));

    if (items.length === 0) {
      showToast('Keranjang belanja kosong');
      return;
    }

    const totalRevenue = getCartTotal();
    let cashPaid = totalRevenue;
    let changeAmount = 0;

    if (currentCheckoutPaymentMethod === 'CASH') {
      const cashVal = parseFloat(cashInput.value) || 0;
      if (cashVal < totalRevenue) {
        showToast('Uang pembayaran masih kurang dari total belanja');
        return;
      }
      cashPaid = cashVal;
      changeAmount = cashVal - totalRevenue;
    } else {
      // QRIS payment is automatically exact
      cashPaid = totalRevenue;
      changeAmount = 0;
    }

    btnConfirm.disabled = true;
    btnConfirm.textContent = 'Memproses...';

    try {
      const createdTx = await fetchAPI('/transactions', {
        method: 'POST',
        body: JSON.stringify({
          items,
          paymentMethod: currentCheckoutPaymentMethod
        })
      });

      closeModal();

      // Show digital thermal receipt modal
      openReceiptModal(
        createdTx.invoiceNumber,
        totalRevenue,
        cashPaid,
        changeAmount,
        createdTx.items || [],
        createdTx.createdAt,
        currentCheckoutPaymentMethod
      );

      if (currentCheckoutPaymentMethod === 'QRIS') {
        showToast('Pembayaran QRIS Berhasil Diterima!');
      } else {
        showToast('Transaksi Tunai Berhasil Disimpan!');
      }

      state.cart = {};
      updateCartBar();
      renderPosProducts();
      await loadProducts();
    } catch {
      // Error handled
    } finally {
      btnConfirm.disabled = false;
      btnConfirm.textContent = currentCheckoutPaymentMethod === 'QRIS'
        ? 'Konfirmasi Pembayaran QRIS'
        : 'Simpan Transaksi (Tunai)';
    }
  });
}

let currentReceiptData = null;

function initReceiptModal() {
  const receiptModal = document.getElementById('modal-receipt');
  const btnCloseReceipt = document.getElementById('btn-close-receipt');
  const btnDoneReceipt = document.getElementById('btn-done-receipt');
  const btnPrintReceipt = document.getElementById('btn-print-receipt');
  const btnWhatsappReceipt = document.getElementById('btn-whatsapp-receipt');

  const closeReceipt = () => receiptModal.classList.add('hidden');
  if (btnCloseReceipt) btnCloseReceipt.addEventListener('click', closeReceipt);
  if (btnDoneReceipt) btnDoneReceipt.addEventListener('click', closeReceipt);

  if (btnPrintReceipt) {
    btnPrintReceipt.addEventListener('click', () => {
      window.print();
    });
  }

  if (btnWhatsappReceipt) {
    btnWhatsappReceipt.addEventListener('click', () => {
      if (!currentReceiptData) return;
      const text = generateWhatsappReceipt(currentReceiptData);
      const url = `https://api.whatsapp.com/send?text=${encodeURIComponent(text)}`;
      window.open(url, '_blank');
    });
  }
}

function generateWhatsappReceipt(data) {
  const itemsText = (data.items || []).map(item => {
    const name = item.productName || item.name || 'Produk';
    const qty = item.quantity || 1;
    const subtotal = formatRupiah(item.subtotalRevenue || (item.sellingPrice * qty) || 0);
    return `• ${name} (${qty}x) = ${subtotal}`;
  }).join('\n');

  const methodLabel = data.paymentMethod === 'QRIS' ? 'QRIS (NON-TUNAI / AUTO-PAS)' : 'TUNAI / CASH';

  return `*WARUNG BAROKAH*\n` +
    `Bukti Pembayaran Sah & Resmi\n` +
    `=============================\n` +
    `No. Nota: ${data.invoice}\n` +
    `Waktu   : ${data.dateTimeStr}\n` +
    `Metode  : ${methodLabel}\n` +
    `=============================\n` +
    `${itemsText}\n` +
    `=============================\n` +
    `Total Tagihan : ${formatRupiah(data.total)}\n` +
    `Uang Diterima : ${formatRupiah(data.cash)}\n` +
    `Kembalian     : ${data.paymentMethod === 'QRIS' ? 'Rp 0 (LUNAS PAS)' : formatRupiah(data.change)}\n` +
    `=============================\n` +
    `Terima kasih telah berbelanja di WARUNG BAROKAH!`;
}

function openReceiptModal(invoice, total, cash, change, items = [], createdAt = null, paymentMethod = 'CASH') {
  const receiptModal = document.getElementById('modal-receipt');
  if (!receiptModal) return;

  const now = createdAt ? new Date(createdAt) : new Date();
  const dateTimeStr = now.toLocaleDateString('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  }) + ' ' + now.toLocaleTimeString('id-ID', {
    hour: '2-digit',
    minute: '2-digit'
  });

  currentReceiptData = {
    invoice: invoice || '-',
    dateTimeStr,
    total,
    cash,
    change,
    items,
    paymentMethod
  };

  const invoiceEl = document.getElementById('receipt-invoice');
  const datetimeEl = document.getElementById('receipt-datetime');
  const totalEl = document.getElementById('receipt-total');
  const cashEl = document.getElementById('receipt-cash');
  const changeEl = document.getElementById('receipt-change');
  const paymentMethodEl = document.getElementById('receipt-payment-method');
  const itemsBody = document.getElementById('receipt-items-body');

  if (invoiceEl) invoiceEl.textContent = invoice || '-';
  if (datetimeEl) datetimeEl.textContent = dateTimeStr;
  if (totalEl) totalEl.textContent = formatRupiah(total);
  if (paymentMethodEl) {
    paymentMethodEl.textContent = paymentMethod === 'QRIS' ? 'QRIS (NON-TUNAI)' : 'TUNAI / CASH';
  }
  if (cashEl) {
    cashEl.textContent = paymentMethod === 'QRIS' ? formatRupiah(total) : formatRupiah(cash);
  }
  if (changeEl) {
    changeEl.textContent = paymentMethod === 'QRIS' ? 'Rp 0 (LUNAS)' : formatRupiah(change);
  }

  if (itemsBody) {
    if (items && items.length > 0) {
      itemsBody.innerHTML = items.map(it => {
        const name = it.productName || it.name || 'Produk';
        const qty = it.quantity || 1;
        const subtotal = formatRupiah(it.subtotalRevenue || (it.sellingPrice * qty) || 0);
        return `
          <tr>
            <td class="item-name">${escapeHtml(name)}</td>
            <td style="text-align: center;">${qty}</td>
            <td style="text-align: right;">${subtotal}</td>
          </tr>
        `;
      }).join('');
    } else {
      itemsBody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: #94A3B8;">-</td></tr>`;
    }
  }

  receiptModal.classList.remove('hidden');
}

function getCartTotal() {
  let totalRevenue = 0;
  Object.entries(state.cart).forEach(([id, qty]) => {
    const p = state.products.find(item => item.id === id);
    if (p) totalRevenue += p.sellingPrice * qty;
  });
  return totalRevenue;
}

function populateCheckoutModal() {
  const itemsContainer = document.getElementById('checkout-items-list');
  const grandTotalEl = document.getElementById('checkout-grand-total');
  const cogsTotalEl = document.getElementById('checkout-cogs-total');
  const profitTotalEl = document.getElementById('checkout-profit-total');
  const cashInput = document.getElementById('checkout-cash-received');

  let totalRevenue = 0;
  let totalCogs = 0;

  const html = Object.entries(state.cart).map(([id, qty]) => {
    const p = state.products.find(item => item.id === id);
    if (!p) return '';
    const lineRevenue = p.sellingPrice * qty;
    const lineCogs = p.costPrice * qty;
    totalRevenue += lineRevenue;
    totalCogs += lineCogs;

    return `
      <div class="checkout-row">
        <span>${escapeHtml(p.name)} (${qty}x)</span>
        <strong>${formatRupiah(lineRevenue)}</strong>
      </div>
    `;
  }).join('');

  const grossProfit = totalRevenue - totalCogs;

  itemsContainer.innerHTML = html;
  const itemBadgeEl = document.getElementById('checkout-item-badge');
  const distinctCount = Object.keys(state.cart).length;
  if (itemBadgeEl) itemBadgeEl.textContent = `${distinctCount} Menu`;

  grandTotalEl.textContent = formatRupiah(totalRevenue);
  cogsTotalEl.textContent = formatRupiah(totalCogs);
  profitTotalEl.textContent = `+${formatRupiah(grossProfit)}`;

  // Defaults to exact cash on open
  cashInput.value = totalRevenue;
  document.querySelectorAll('.cash-chip').forEach(c => {
    if (c.getAttribute('data-val') === 'exact') c.classList.add('active');
    else c.classList.remove('active');
  });

  calculateChange();

  // Refresh QRIS display and nominal
  renderQrisDisplay();

  const accordionCash = document.getElementById('accordion-cash');
  const accordionQris = document.getElementById('accordion-qris');
  const btnConfirm = document.getElementById('btn-confirm-checkout');

  if (currentCheckoutPaymentMethod === 'QRIS') {
    if (accordionQris) accordionQris.classList.add('active');
    if (accordionCash) accordionCash.classList.remove('active');
    if (btnConfirm) btnConfirm.textContent = 'Konfirmasi Pembayaran QRIS';
  } else {
    if (accordionCash) accordionCash.classList.add('active');
    if (accordionQris) accordionQris.classList.remove('active');
    if (btnConfirm) btnConfirm.textContent = 'Simpan Transaksi (Tunai)';
  }
}

function calculateChange() {
  const grandTotalEl = document.getElementById('checkout-grand-total');
  const cashInput = document.getElementById('checkout-cash-received');
  const changeEl = document.getElementById('checkout-change-amount');

  const totalRevenue = getCartTotal();
  const cash = parseFloat(cashInput.value) || 0;
  const change = cash - totalRevenue;

  if (change >= 0) {
    changeEl.textContent = formatRupiah(change);
    changeEl.style.color = 'var(--color-primary)';
  } else {
    changeEl.textContent = `Kurang ${formatRupiah(Math.abs(change))}`;
    changeEl.style.color = 'var(--color-danger)';
  }
}

// Catalog List & Modal
function renderCatalogList() {
  const container = document.getElementById('catalog-list');
  if (!container) return;

  const filtered = state.products.filter(p => {
    if (state.catalogSearch && !p.name.toLowerCase().includes(state.catalogSearch.toLowerCase())) {
      return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>Belum ada produk terdaftar. Klik "+ Tambah Menu" untuk membuat baru.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map(p => `
    <div class="catalog-item-card">
      <div class="item-top-row">
        <span class="name">${escapeHtml(p.name)}</span>
        <span class="category">${escapeHtml(p.category)}</span>
      </div>
      <div class="item-pricing-row">
        <div class="price-col">
          <span class="col-label">Harga Jual</span>
          <span class="col-val">${formatRupiah(p.sellingPrice)}</span>
        </div>
        <div class="price-col">
          <span class="col-label">Modal Beli</span>
          <span class="col-val">${formatRupiah(p.costPrice)}</span>
        </div>
        <div class="price-col">
          <span class="col-label">Margin Laba</span>
          <span class="col-val margin-val">${formatRupiah(p.unitMargin)} (${p.marginPercentage}%)</span>
        </div>
      </div>
      <div class="item-actions-row">
        <button class="btn-icon-text" onclick="editProduct('${p.id}')">Edit</button>
        <button class="btn-icon-text danger" onclick="deleteProduct('${p.id}')">Hapus</button>
      </div>
    </div>
  `).join('');
}

function initProductModal() {
  const modal = document.getElementById('modal-product');
  const btnAdd = document.getElementById('btn-add-product');
  const btnPosAdd = document.getElementById('btn-pos-add-product');
  const btnClose = document.getElementById('btn-close-product');
  const btnCancel = document.getElementById('btn-cancel-product');
  const form = document.getElementById('form-product');
  const title = document.getElementById('modal-product-title');

  const costInput = document.getElementById('product-cost-price');
  const sellInput = document.getElementById('product-selling-price');
  const unitProfitEl = document.getElementById('calc-unit-profit');
  const marginPercentEl = document.getElementById('calc-margin-percent');

  const updateCalculatedMargin = () => {
    const cost = parseFloat(costInput.value) || 0;
    const sell = parseFloat(sellInput.value) || 0;
    const profit = sell - cost;
    const margin = sell > 0 ? Math.round((profit / sell) * 1000) / 10 : 0;
    unitProfitEl.textContent = formatRupiah(profit);
    marginPercentEl.textContent = `${margin}%`;
  };

  costInput.addEventListener('input', updateCalculatedMargin);
  sellInput.addEventListener('input', updateCalculatedMargin);

  window.openAddProductModal = () => {
    state.editingProductId = null;
    title.textContent = 'Tambah Menu Produk';
    form.reset();
    updateCalculatedMargin();
    modal.classList.remove('hidden');
  };

  if (btnAdd) btnAdd.addEventListener('click', window.openAddProductModal);
  if (btnPosAdd) btnPosAdd.addEventListener('click', window.openAddProductModal);

  const closeModal = () => modal.classList.add('hidden');
  btnClose.addEventListener('click', closeModal);
  btnCancel.addEventListener('click', closeModal);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('product-name').value;
    const category = document.getElementById('product-category').value;
    const costPrice = parseFloat(costInput.value);
    const sellingPrice = parseFloat(sellInput.value);

    try {
      if (state.editingProductId) {
        await fetchAPI(`/products/${state.editingProductId}`, {
          method: 'PUT',
          body: JSON.stringify({ name, category, costPrice, sellingPrice })
        });
        showToast(`Menu "${name}" berhasil diperbarui!`);
      } else {
        await fetchAPI('/products', {
          method: 'POST',
          body: JSON.stringify({ name, category, costPrice, sellingPrice })
        });
        showToast(`Menu "${name}" langsung tersedia di Kasir!`);
      }
      closeModal();
      await loadProducts();
    } catch {
      // Handled
    }
  });
}

window.editProduct = function(id) {
  const product = state.products.find(p => p.id === id);
  if (!product) return;
  state.editingProductId = id;

  document.getElementById('modal-product-title').textContent = 'Edit Menu Produk';
  document.getElementById('product-name').value = product.name;
  document.getElementById('product-category').value = product.category;
  document.getElementById('product-cost-price').value = product.costPrice;
  document.getElementById('product-selling-price').value = product.sellingPrice;

  const profit = product.sellingPrice - product.costPrice;
  document.getElementById('calc-unit-profit').textContent = formatRupiah(profit);
  document.getElementById('calc-margin-percent').textContent = `${product.marginPercentage}%`;

  document.getElementById('modal-product').classList.remove('hidden');
};

window.deleteProduct = async function(id) {
  if (!confirm('Yakin ingin menghapus menu ini dari daftar?')) return;
  try {
    await fetchAPI(`/products/${id}`, { method: 'DELETE' });
    showToast('Menu telah dihapus');
    delete state.cart[id];
    updateCartBar();
    await loadProducts();
  } catch {
    // Handled
  }
};

// Expenses Functions
async function loadExpenses() {
  try {
    const data = await fetchAPI('/expenses');
    state.expenses = data;
    renderExpensesList();
  } catch {
    // Handled
  }
}

function renderExpensesList() {
  const container = document.getElementById('expenses-list');
  const monthTotalEl = document.getElementById('expense-month-total');
  if (!container) return;

  const total = state.expenses.reduce((sum, e) => sum + e.amount, 0);
  if (monthTotalEl) monthTotalEl.textContent = formatRupiah(total);

  if (state.expenses.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>Belum ada catatan biaya operasional.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = state.expenses.map(e => `
    <div class="expense-item">
      <div class="expense-item-info">
        <div class="category">${escapeHtml(e.category)}</div>
        ${e.notes ? `<div class="notes">${escapeHtml(e.notes)}</div>` : ''}
        <div class="date">${escapeHtml(e.expenseDate)}</div>
      </div>
      <div class="expense-item-amount">
        <span class="amount">-${formatRupiah(e.amount)}</span>
        <button class="btn-icon-text danger" style="padding: 2px 6px;" onclick="deleteExpense('${e.id}')">Hapus</button>
      </div>
    </div>
  `).join('');
}

function initExpenseModal() {
  const modal = document.getElementById('modal-expense');
  const btnAdd = document.getElementById('btn-add-expense');
  const btnClose = document.getElementById('btn-close-expense');
  const btnCancel = document.getElementById('btn-cancel-expense');
  const form = document.getElementById('form-expense');
  const dateInput = document.getElementById('expense-date');

  btnAdd.addEventListener('click', () => {
    form.reset();
    dateInput.value = new Date().toISOString().split('T')[0];
    modal.classList.remove('hidden');
  });

  const closeModal = () => modal.classList.add('hidden');
  btnClose.addEventListener('click', closeModal);
  btnCancel.addEventListener('click', closeModal);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const category = document.getElementById('expense-category').value;
    const amount = parseFloat(document.getElementById('expense-amount').value);
    const expenseDate = dateInput.value;
    const notes = document.getElementById('expense-notes').value;

    try {
      await fetchAPI('/expenses', {
        method: 'POST',
        body: JSON.stringify({ category, amount, expenseDate, notes })
      });
      showToast('Biaya operasional dicatat');
      closeModal();
      await loadExpenses();
    } catch {
      // Handled
    }
  });
}

window.deleteExpense = async function(id) {
  if (!confirm('Hapus pencatatan pengeluaran ini?')) return;
  try {
    await fetchAPI(`/expenses/${id}`, { method: 'DELETE' });
    showToast('Biaya operasional dihapus');
    await loadExpenses();
  } catch {
    // Handled
  }
};

// Analytics & Charts Functions
async function loadAnalytics() {
  const period = state.analyticsPeriod;
  try {
    const summary = await fetchAPI(`/analytics/summary?period=${period}`);
    const chartData = await fetchAPI(`/analytics/charts?period=${period}`);
    state.lastChartData = chartData;

    document.getElementById('metric-revenue-val').textContent = formatRupiah(summary.totalRevenue);
    document.getElementById('metric-cogs-val').textContent = formatRupiah(summary.totalCogs);
    document.getElementById('metric-gross-val').textContent = formatRupiah(summary.grossProfit);
    document.getElementById('metric-gross-margin').textContent = `${summary.grossMarginPercent}% Margin`;

    document.getElementById('metric-net-val').textContent = formatRupiah(summary.netProfit);
    document.getElementById('metric-net-margin').textContent = `${summary.netMarginPercent}% Margin`;

    document.getElementById('analytics-expense-total').textContent = `-${formatRupiah(summary.totalExpenses)}`;

    const totalCustEl = document.getElementById('metric-total-customers');
    if (totalCustEl) {
      totalCustEl.textContent = `${summary.totalCustomers || 0} Pembeli`;
    }

    drawChart(chartData);
    drawCustomersChart(chartData);
  } catch (e) {
    console.error('Analytics load error:', e);
  }
}

function initPeriodTabs() {
  const tabs = document.querySelectorAll('.period-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      state.analyticsPeriod = tab.getAttribute('data-period');
      loadAnalytics();
    });
  });
}

// Date helpers for responsive charts
function formatChartDate(isoDateStr, totalPoints) {
  if (!isoDateStr) return '';
  const parts = isoDateStr.split('-');
  if (parts.length < 3) return isoDateStr;
  const day = parseInt(parts[2], 10);
  const month = parseInt(parts[1], 10);

  if (totalPoints <= 3) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
    return `${day} ${months[month - 1] || month}`;
  }
  return `${String(day).padStart(2, '0')}/${String(month).padStart(2, '0')}`;
}

function getAdaptiveLabelIndices(totalPoints, chartWidth) {
  const indices = new Set();
  if (totalPoints <= 7) {
    for (let i = 0; i < totalPoints; i++) indices.add(i);
    return indices;
  }

  // Allow ~45px per label minimum to eliminate overlap
  const maxLabels = Math.max(3, Math.min(7, Math.floor(chartWidth / 45)));
  const step = Math.max(2, Math.ceil(totalPoints / maxLabels));

  for (let i = 0; i < totalPoints; i += step) {
    if (totalPoints - 1 - i >= Math.floor(step * 0.55)) {
      indices.add(i);
    }
  }
  // Always include the latest day (today / last point)
  indices.add(totalPoints - 1);
  return indices;
}

function drawChart(dataPoints) {
  const canvas = document.getElementById('profit-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const isDark = isDarkMode();

  // Handle high-dpi displays and responsive sizing
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = rect.width > 0 ? rect.width : 360;
  const height = 220;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.scale(dpr, dpr);

  ctx.clearRect(0, 0, width, height);

  if (!dataPoints || dataPoints.length === 0) {
    ctx.fillStyle = isDark ? '#94A3B8' : '#64748B';
    ctx.font = '12px Plus Jakarta Sans';
    ctx.textAlign = 'center';
    ctx.fillText('Belum ada data untuk periode ini', width / 2, height / 2);
    return;
  }

  // Padding
  const padLeft = 45;
  const padBottom = 30;
  const padTop = 20;
  const padRight = 15;
  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  // Find max value
  let maxVal = 10000;
  dataPoints.forEach(p => {
    if (p.revenue > maxVal) maxVal = p.revenue;
    if (p.grossProfit > maxVal) maxVal = p.grossProfit;
    if (p.netProfit > maxVal) maxVal = p.netProfit;
  });
  maxVal = Math.ceil(maxVal * 1.15); // Add headroom

  // Draw grid lines
  ctx.strokeStyle = isDark ? '#334155' : '#E2E8F0';
  ctx.lineWidth = 1;
  ctx.fillStyle = isDark ? '#94A3B8' : '#64748B';
  ctx.font = '10px Plus Jakarta Sans';
  ctx.textAlign = 'right';

  const gridSteps = 4;
  for (let i = 0; i <= gridSteps; i++) {
    const yVal = (maxVal / gridSteps) * i;
    const yPos = height - padBottom - (i / gridSteps) * chartH;

    ctx.beginPath();
    ctx.moveTo(padLeft, yPos);
    ctx.lineTo(width - padRight, yPos);
    ctx.stroke();

    const label = yVal >= 1000000 ? `${(yVal / 1000000).toFixed(1)}M` : (yVal >= 1000 ? `${Math.round(yVal / 1000)}k` : yVal);
    ctx.fillText(label, padLeft - 6, yPos + 3);
  }

  // Draw bars for each data point
  const n = dataPoints.length;
  const groupW = chartW / n;
  // Dynamic bar group width to ensure bars never overflow their slot
  const usableW = Math.max(3, groupW * 0.75);
  const barW = Math.max(1.2, Math.min(8.5, usableW / 3));
  const total3BarsW = barW * 3;
  const barGap = barW > 3 ? 1 : (barW > 2 ? 0.5 : 0);

  const labelIndices = getAdaptiveLabelIndices(n, chartW);

  dataPoints.forEach((point, idx) => {
    const groupCenter = padLeft + idx * groupW + groupW / 2;

    const hRev = maxVal > 0 ? (point.revenue / maxVal) * chartH : 0;
    const hGross = maxVal > 0 ? (point.grossProfit / maxVal) * chartH : 0;
    const hNet = maxVal > 0 ? Math.max(0, (point.netProfit / maxVal) * chartH) : 0;

    const startX = groupCenter - total3BarsW / 2;

    // Revenue Bar
    ctx.fillStyle = isDark ? '#38BDF8' : '#0284C7';
    if (hRev > 0) {
      ctx.fillRect(startX, height - padBottom - hRev, Math.max(1, barW - barGap), hRev);
    } else {
      ctx.fillRect(startX, height - padBottom - 1.5, Math.max(1, barW - barGap), 1.5);
    }

    // Gross Profit Bar
    ctx.fillStyle = isDark ? '#2DD4BF' : '#0D9488';
    if (hGross > 0) {
      ctx.fillRect(startX + barW, height - padBottom - hGross, Math.max(1, barW - barGap), hGross);
    } else {
      ctx.fillRect(startX + barW, height - padBottom - 1.5, Math.max(1, barW - barGap), 1.5);
    }

    // Net Profit Bar
    ctx.fillStyle = isDark ? '#4ADE80' : '#15803D';
    if (hNet > 0) {
      ctx.fillRect(startX + barW * 2, height - padBottom - hNet, Math.max(1, barW - barGap), hNet);
    } else {
      ctx.fillRect(startX + barW * 2, height - padBottom - 1.5, Math.max(1, barW - barGap), 1.5);
    }

    // X-axis label (adaptive, collision-free)
    if (labelIndices.has(idx)) {
      ctx.fillStyle = isDark ? '#94A3B8' : '#64748B';
      ctx.font = '9px Plus Jakarta Sans';
      ctx.textAlign = 'center';
      const labelText = formatChartDate(point.date, n);
      ctx.fillText(labelText, groupCenter, height - 10);

      // Tick mark on X axis
      ctx.strokeStyle = isDark ? '#334155' : '#CBD5E1';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(groupCenter, height - padBottom);
      ctx.lineTo(groupCenter, height - padBottom + 3);
      ctx.stroke();
    }
  });
}

function drawCustomersChart(dataPoints) {
  const canvas = document.getElementById('customers-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const isDark = isDarkMode();

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = rect.width > 0 ? rect.width : 360;
  const height = 180;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.scale(dpr, dpr);

  ctx.clearRect(0, 0, width, height);

  if (!dataPoints || dataPoints.length === 0) {
    ctx.fillStyle = isDark ? '#94A3B8' : '#64748B';
    ctx.font = '12px Plus Jakarta Sans';
    ctx.textAlign = 'center';
    ctx.fillText('Belum ada data transaksi pembeli', width / 2, height / 2);
    return;
  }

  // Padding
  const padLeft = 35;
  const padBottom = 28;
  const padTop = 24;
  const padRight = 15;
  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  // Find max customer count
  let maxVal = 5;
  dataPoints.forEach(p => {
    const count = p.customerCount || 0;
    if (count > maxVal) maxVal = count;
  });
  maxVal = Math.ceil(maxVal * 1.25);

  // Draw grid lines
  ctx.strokeStyle = isDark ? '#334155' : '#E2E8F0';
  ctx.lineWidth = 1;
  ctx.fillStyle = isDark ? '#94A3B8' : '#78716C';
  ctx.font = '10px Plus Jakarta Sans';
  ctx.textAlign = 'right';

  const gridSteps = 3;
  for (let i = 0; i <= gridSteps; i++) {
    const yVal = Math.round((maxVal / gridSteps) * i);
    const yPos = height - padBottom - (i / gridSteps) * chartH;

    ctx.beginPath();
    ctx.moveTo(padLeft, yPos);
    ctx.lineTo(width - padRight, yPos);
    ctx.stroke();

    ctx.fillText(`${yVal}`, padLeft - 6, yPos + 3);
  }

  // Draw single prominent bar for each day's customer count
  const n = dataPoints.length;
  const groupW = chartW / n;
  const barW = Math.max(3, Math.min(22, groupW * 0.65));

  const labelIndices = getAdaptiveLabelIndices(n, chartW);

  dataPoints.forEach((point, idx) => {
    const groupCenter = padLeft + idx * groupW + groupW / 2;
    const count = point.customerCount || 0;
    const barH = maxVal > 0 ? (count / maxVal) * chartH : 0;
    const barX = groupCenter - barW / 2;
    const barY = height - padBottom - barH;

    // Draw Bar
    ctx.fillStyle = count > 0 ? (isDark ? '#4ADE80' : '#15803D') : (isDark ? '#334155' : '#E2E8F0');
    if (barH > 0) {
      ctx.fillRect(barX, barY, barW, barH);
    } else {
      ctx.fillRect(barX, height - padBottom - 1.5, barW, 1.5);
    }

    // Number of customers above bar:
    if (n <= 7 || count > 0) {
      ctx.fillStyle = count > 0 ? (isDark ? '#4ADE80' : '#15803D') : (isDark ? '#64748B' : '#94A3B8');
      ctx.font = n > 7 ? 'bold 9px Plus Jakarta Sans' : 'bold 10px Plus Jakarta Sans';
      ctx.textAlign = 'center';
      const textY = barH > 0 ? barY - 4 : height - padBottom - 5;
      ctx.fillText(`${count}`, groupCenter, textY);
    }

    // X-axis label (adaptive, collision-free)
    if (labelIndices.has(idx)) {
      ctx.fillStyle = isDark ? '#94A3B8' : '#64748B';
      ctx.font = '9px Plus Jakarta Sans';
      ctx.textAlign = 'center';
      const labelText = formatChartDate(point.date, n);
      ctx.fillText(labelText, groupCenter, height - 8);

      // Tick mark on X axis
      ctx.strokeStyle = isDark ? '#334155' : '#E7E5E4';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(groupCenter, height - padBottom);
      ctx.lineTo(groupCenter, height - padBottom + 3);
      ctx.stroke();
    }
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Shop Full Report Modal & CSV Download
function initShopReportModal() {
  const modal = document.getElementById('modal-shop-report');
  const btnOpen = document.getElementById('btn-open-print-report');
  const btnClose = document.getElementById('btn-close-shop-report');
  const btnCancel = document.getElementById('btn-cancel-shop-report');
  const btnPrintTrigger = document.getElementById('btn-trigger-print-report');
  const btnDownloadCsv = document.getElementById('btn-download-csv-report');

  if (!modal) return;

  const closeModal = () => modal.classList.add('hidden');
  if (btnClose) btnClose.addEventListener('click', closeModal);
  if (btnCancel) btnCancel.addEventListener('click', closeModal);

  async function fetchCurrentReportData() {
    const period = state.analyticsPeriod || 'today';
    const periodLabels = {
      'today': '1 Hari (Hari Ini)',
      '3d': '3 Hari Terakhir',
      '7d': '1 Minggu Terakhir',
      '30d': '1 Bulan Terakhir'
    };
    const periodLabel = periodLabels[period] || period;

    const [summary, transactions, expenses] = await Promise.all([
      fetchAPI(`/analytics/summary?period=${period}`),
      fetchAPI('/transactions'),
      fetchAPI('/expenses')
    ]);

    const now = new Date();
    const endDate = now.toISOString().split('T')[0];
    let startDate = endDate;
    if (period === '3d') {
      const d = new Date(now);
      d.setDate(d.getDate() - 2);
      startDate = d.toISOString().split('T')[0];
    } else if (period === '7d') {
      const d = new Date(now);
      d.setDate(d.getDate() - 6);
      startDate = d.toISOString().split('T')[0];
    } else if (period === '30d') {
      const d = new Date(now);
      d.setDate(d.getDate() - 29);
      startDate = d.toISOString().split('T')[0];
    }

    const effectiveStartDate = summary.startDate || startDate;
    const effectiveEndDate = summary.endDate || endDate;
    summary.startDate = effectiveStartDate;
    summary.endDate = effectiveEndDate;

    const periodTransactions = (transactions || []).filter(t => {
      if (!t.createdAt) return false;
      const d = t.createdAt.slice(0, 10);
      return d >= effectiveStartDate && d <= effectiveEndDate;
    });

    const periodExpenses = (expenses || []).filter(e => {
      if (!e.expenseDate) return false;
      return e.expenseDate >= effectiveStartDate && e.expenseDate <= effectiveEndDate;
    });

    return {
      period,
      periodLabel,
      summary,
      periodTransactions,
      periodExpenses
    };
  }

  // Open & Populate Report Modal
  if (btnOpen) {
    btnOpen.addEventListener('click', async () => {
      try {
        const { periodLabel, summary, periodTransactions, periodExpenses } = await fetchCurrentReportData();

        const rangeStr = `${summary.startDate} s/d ${summary.endDate}`;
        const now = new Date();
        const printedAtStr = now.toLocaleDateString('id-ID', {
          day: 'numeric',
          month: 'short',
          year: 'numeric'
        }) + ' ' + now.toLocaleTimeString('id-ID', {
          hour: '2-digit',
          minute: '2-digit'
        });

        // Populate Header Metadata
        const periodNameEl = document.getElementById('report-period-name');
        const rangeEl = document.getElementById('report-date-range');
        const printedAtEl = document.getElementById('report-printed-at');
        if (periodNameEl) periodNameEl.textContent = periodLabel;
        if (rangeEl) rangeEl.textContent = rangeStr;
        if (printedAtEl) printedAtEl.textContent = printedAtStr;

        // Populate Financial Executive Summary
        const repCustomers = document.getElementById('rep-total-customers');
        const repRevenue = document.getElementById('rep-total-revenue');
        const repCogs = document.getElementById('rep-total-cogs');
        const repGross = document.getElementById('rep-gross-profit');
        const repGrossMargin = document.getElementById('rep-gross-margin');
        const repExpenses = document.getElementById('rep-total-expenses');
        const repNet = document.getElementById('rep-net-profit');
        const repNetMargin = document.getElementById('rep-net-margin');

        if (repCustomers) repCustomers.textContent = `${summary.totalCustomers || periodTransactions.length} Orang`;
        if (repRevenue) repRevenue.textContent = formatRupiah(summary.totalRevenue);
        if (repCogs) repCogs.textContent = formatRupiah(summary.totalCogs);
        if (repGross) repGross.textContent = formatRupiah(summary.grossProfit);
        if (repGrossMargin) repGrossMargin.textContent = `${summary.grossMarginPercent}%`;
        if (repExpenses) repExpenses.textContent = `-${formatRupiah(summary.totalExpenses)}`;
        if (repNet) repNet.textContent = formatRupiah(summary.netProfit);
        if (repNetMargin) repNetMargin.textContent = `${summary.netMarginPercent}%`;

        // Populate Expenses Table
        const expBody = document.getElementById('report-expenses-body');
        if (expBody) {
          if (periodExpenses.length === 0) {
            expBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #94A3B8; padding: 12px;">Tidak ada pengeluaran operasional pada periode ini.</td></tr>';
          } else {
            expBody.innerHTML = periodExpenses.map(e => `
              <tr>
                <td><strong>${escapeHtml(e.category)}</strong></td>
                <td>${escapeHtml(e.expenseDate)}</td>
                <td>${escapeHtml(e.notes || '-')}</td>
                <td style="text-align: right; color: #DC2626; font-weight: 600;">-${formatRupiah(e.amount)}</td>
              </tr>
            `).join('');
          }
        }

        // Populate Sales Transactions Table
        const txBody = document.getElementById('report-transactions-body');
        if (txBody) {
          if (periodTransactions.length === 0) {
            txBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #94A3B8; padding: 12px;">Tidak ada transaksi penjualan pada periode ini.</td></tr>';
          } else {
            txBody.innerHTML = periodTransactions.map(t => {
              const d = new Date(t.createdAt);
              const timeStr = d.toLocaleDateString('id-ID', {
                day: '2-digit',
                month: '2-digit',
                year: '2-digit'
              }) + ' ' + d.toLocaleTimeString('id-ID', {
                hour: '2-digit',
                minute: '2-digit'
              });
              return `
                <tr>
                  <td><strong>${escapeHtml(t.invoiceNumber)}</strong></td>
                  <td>${escapeHtml(timeStr)}</td>
                  <td style="text-align: right;">${formatRupiah(t.totalRevenue)}</td>
                  <td style="text-align: right; color: #64748B;">${formatRupiah(t.totalCogs)}</td>
                  <td style="text-align: right; color: #16A34A; font-weight: 600;">${formatRupiah(t.grossProfit)}</td>
                </tr>
              `;
            }).join('');
          }
        }

        modal.classList.remove('hidden');
      } catch (err) {
        console.error('Failed to prepare shop report:', err);
        showToast('Gagal memuat data laporan');
      }
    });
  }

  // Trigger Print Report
  if (btnPrintTrigger) {
    btnPrintTrigger.addEventListener('click', () => {
      document.body.classList.add('printing-report');
      window.print();
      const cleanUp = () => document.body.classList.remove('printing-report');
      window.addEventListener('afterprint', cleanUp, { once: true });
      setTimeout(cleanUp, 1500);
    });
  }

  // Trigger CSV Download
  if (btnDownloadCsv) {
    btnDownloadCsv.addEventListener('click', async () => {
      try {
        const { period, periodLabel, summary, periodTransactions, periodExpenses } = await fetchCurrentReportData();

        const csvCell = (val) => {
          if (val === null || val === undefined) return '""';
          return '"' + String(val).replace(/"/g, '""') + '"';
        };

        const now = new Date();
        const printedAtStr = now.toLocaleDateString('id-ID', {
          day: 'numeric',
          month: 'short',
          year: 'numeric'
        }) + ' ' + now.toLocaleTimeString('id-ID', {
          hour: '2-digit',
          minute: '2-digit'
        });

        const csvRows = [];
        // 1. Header
        csvRows.push([csvCell('LAPORAN KEUANGAN & PENJUALAN - WARUNG BAROKAH')].join(','));
        csvRows.push([csvCell('Periode Laporan'), csvCell(periodLabel)].join(','));
        csvRows.push([csvCell('Rentang Tanggal'), csvCell(`${summary.startDate} s/d ${summary.endDate}`)].join(','));
        csvRows.push([csvCell('Waktu Download'), csvCell(printedAtStr)].join(','));
        csvRows.push([]);

        // 2. Financial Summary
        csvRows.push([csvCell('I. REKAPITULASI FINANSIAL')].join(','));
        csvRows.push([csvCell('Indikator Keuangan'), csvCell('Nilai Nominal (Rp)'), csvCell('Keterangan / Margin')].join(','));
        csvRows.push([csvCell('Total Pelanggan / Transaksi'), csvCell(summary.totalCustomers || periodTransactions.length), csvCell('Pembeli')].join(','));
        csvRows.push([csvCell('Total Penjualan (Omzet)'), csvCell(summary.totalRevenue), csvCell(formatRupiah(summary.totalRevenue))].join(','));
        csvRows.push([csvCell('Total Modal Pokok (COGS)'), csvCell(summary.totalCogs), csvCell(formatRupiah(summary.totalCogs))].join(','));
        csvRows.push([csvCell('Laba Kotor (Gross Profit)'), csvCell(summary.grossProfit), csvCell(`${summary.grossMarginPercent}% Margin`)].join(','));
        csvRows.push([csvCell('Total Biaya Operasional'), csvCell(summary.totalExpenses), csvCell(`-${formatRupiah(summary.totalExpenses)}`)].join(','));
        csvRows.push([csvCell('Laba Bersih (Net Profit)'), csvCell(summary.netProfit), csvCell(`${summary.netMarginPercent}% Margin`)].join(','));
        csvRows.push([]);

        // 3. Operational Expenses
        csvRows.push([csvCell('II. RINCIAN PENGELUARAN OPERASIONAL')].join(','));
        csvRows.push([csvCell('Kategori'), csvCell('Tanggal'), csvCell('Catatan'), csvCell('Jumlah Pengeluaran (Rp)')].join(','));
        if (periodExpenses.length === 0) {
          csvRows.push([csvCell('Tidak ada catatan pengeluaran'), csvCell('-'), csvCell('-'), csvCell(0)].join(','));
        } else {
          periodExpenses.forEach(e => {
            csvRows.push([
              csvCell(e.category),
              csvCell(e.expenseDate),
              csvCell(e.notes || '-'),
              csvCell(e.amount)
            ].join(','));
          });
        }
        csvRows.push([]);

        // 4. Sales Transactions
        csvRows.push([csvCell('III. DAFTAR TRANSAKSI PENJUALAN')].join(','));
        csvRows.push([csvCell('No. Nota'), csvCell('Waktu Transaksi'), csvCell('Metode Bayar'), csvCell('Total Omzet (Rp)'), csvCell('Modal Produk (Rp)'), csvCell('Laba Kotor (Rp)')].join(','));
        if (periodTransactions.length === 0) {
          csvRows.push([csvCell('Tidak ada transaksi penjualan'), csvCell('-'), csvCell('-'), csvCell(0), csvCell(0), csvCell(0)].join(','));
        } else {
          periodTransactions.forEach(t => {
            csvRows.push([
              csvCell(t.invoiceNumber),
              csvCell(t.createdAt),
              csvCell(t.paymentMethod || 'TUNAI'),
              csvCell(t.totalRevenue),
              csvCell(t.totalCogs),
              csvCell(t.grossProfit)
            ].join(','));
          });
        }

        const csvString = csvRows.join('\r\n');
        const blob = new Blob(['\uFEFF' + csvString], { type: 'text/csv;charset=utf-8;' });
        const downloadUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = `Laporan_WARUNG_BAROKAH_${period}_${summary.startDate}_sd_${summary.endDate}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(downloadUrl);

        showToast(`Laporan CSV (${periodLabel}) berhasil didownload!`);
      } catch (err) {
        console.error('Failed to download CSV report:', err);
        showToast('Gagal mengunduh laporan CSV');
      }
    });
  }
}

// Initialization on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initNavigation();
  initCheckoutModal();
  initReceiptModal();
  initProductModal();
  initExpenseModal();
  initPeriodTabs();
  initShopReportModal();

  // Category filter chips in POS
  const chips = document.querySelectorAll('#pos-category-chips .chip');
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      chips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.selectedCategory = chip.getAttribute('data-category');
      renderPosProducts();
    });
  });

  // Search input listeners
  const posSearch = document.getElementById('pos-search');
  if (posSearch) {
    posSearch.addEventListener('input', (e) => {
      state.posSearch = e.target.value;
      renderPosProducts();
    });
  }

  const catalogSearch = document.getElementById('catalog-search');
  if (catalogSearch) {
    catalogSearch.addEventListener('input', (e) => {
      state.catalogSearch = e.target.value;
      renderCatalogList();
    });
  }

  // Initial fetch
  loadProducts();
  loadExpenses();

  // Responsive chart redraw on window resize or device orientation change
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (state.activeScreen === 'screen-analytics') {
        loadAnalytics();
      }
    }, 150);
  });
});
