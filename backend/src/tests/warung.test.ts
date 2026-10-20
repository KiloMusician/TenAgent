import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'fs';
import path from 'path';
import { calculateProductMargin } from '../domain/entities/Product';
import {
  JsonStorage,
  JsonProductRepository,
  JsonTransactionRepository,
  JsonExpenseRepository,
  JsonAnalyticsRepository
} from '../data/repositories/JsonDataRepository';
import { ProductUseCases } from '../domain/usecases/ProductUseCases';
import { TransactionUseCases } from '../domain/usecases/TransactionUseCases';
import { ExpenseUseCases } from '../domain/usecases/ExpenseUseCases';
import { AnalyticsUseCases } from '../domain/usecases/AnalyticsUseCases';

describe('Warung POS Domain & Calculation Engine Tests', () => {
  const testStorageDir = path.join(__dirname, '../../test-storage');

  before(() => {
    if (fs.existsSync(testStorageDir)) {
      fs.rmSync(testStorageDir, { recursive: true, force: true });
    }
  });

  after(() => {
    if (fs.existsSync(testStorageDir)) {
      fs.rmSync(testStorageDir, { recursive: true, force: true });
    }
  });

  it('calculates product margin and percentage correctly', () => {
    const { unitMargin, marginPercentage } = calculateProductMargin(1500, 4000);
    assert.strictEqual(unitMargin, 2500);
    assert.strictEqual(marginPercentage, 62.5);

    const zeroMargin = calculateProductMargin(5000, 5000);
    assert.strictEqual(zeroMargin.unitMargin, 0);
    assert.strictEqual(zeroMargin.marginPercentage, 0);

    const zeroSelling = calculateProductMargin(1000, 0);
    assert.strictEqual(zeroSelling.unitMargin, -1000);
    assert.strictEqual(zeroSelling.marginPercentage, 0);
  });

  it('creates and lists products with positive margins', async () => {
    const storage = new JsonStorage(testStorageDir);
    const productRepo = new JsonProductRepository(storage);
    const productUseCases = new ProductUseCases(productRepo);

    const created = await productUseCases.createProduct({
      name: 'Kopi Hitam Manis',
      category: 'Minuman',
      costPrice: 2000,
      sellingPrice: 5000
    });

    assert.strictEqual(created.name, 'Kopi Hitam Manis');
    assert.strictEqual(created.unitMargin, 3000);
    assert.strictEqual(created.marginPercentage, 60);

    const list = await productUseCases.listProducts('Minuman');
    assert.ok(list.some(p => p.id === created.id));
  });

  it('rejects product creation with negative pricing', async () => {
    const storage = new JsonStorage(testStorageDir);
    const productRepo = new JsonProductRepository(storage);
    const productUseCases = new ProductUseCases(productRepo);

    await assert.rejects(
      async () => {
        await productUseCases.createProduct({
          name: 'Invalid Item',
          costPrice: -100,
          sellingPrice: 1000
        });
      },
      /Cost price must be non-negative/
    );
  });

  it('records transactions, computes COGS, and derives gross profit correctly', async () => {
    const storage = new JsonStorage(testStorageDir);
    const productRepo = new JsonProductRepository(storage);
    const txRepo = new JsonTransactionRepository(storage);
    const txUseCases = new TransactionUseCases(txRepo, productRepo);

    const prod1 = await productRepo.create({
      name: 'Nasi Goreng',
      category: 'Makanan',
      costPrice: 8000,
      sellingPrice: 15000
    });

    const prod2 = await productRepo.create({
      name: 'Es Teh Manis',
      category: 'Minuman',
      costPrice: 1000,
      sellingPrice: 3000
    });

    const tx = await txUseCases.recordSale({
      paymentMethod: 'CASH',
      items: [
        { productId: prod1.id, quantity: 2 }, // 2x 15000 = 30000 rev, 2x 8000 = 16000 cogs
        { productId: prod2.id, quantity: 3 }  // 3x 3000 = 9000 rev, 3x 1000 = 3000 cogs
      ]
    });

    assert.strictEqual(tx.totalRevenue, 39000);
    assert.strictEqual(tx.totalCogs, 19000);
    assert.strictEqual(tx.grossProfit, 20000); // 39000 - 19000 = 20000
    assert.strictEqual(tx.items.length, 2);
  });

  it('logs operational expenses and calculates net profit', async () => {
    const storage = new JsonStorage(testStorageDir);
    const expenseRepo = new JsonExpenseRepository(storage);
    const analyticsRepo = new JsonAnalyticsRepository(storage);
    const expenseUseCases = new ExpenseUseCases(expenseRepo);
    const analyticsUseCases = new AnalyticsUseCases(analyticsRepo);

    const expense = await expenseUseCases.recordExpense({
      category: 'Kantong Plastik',
      amount: 5000,
      notes: 'Beli kresek bening'
    });

    assert.strictEqual(expense.amount, 5000);
    assert.strictEqual(expense.category, 'Kantong Plastik');

    const summary = await analyticsUseCases.getSummary('today');
    // Net Profit = Gross Profit - Total Expenses
    assert.strictEqual(summary.totalRevenue, 39000);
    assert.strictEqual(summary.grossProfit, 20000);
    assert.ok(summary.totalExpenses >= 5000);
    assert.strictEqual(summary.netProfit, summary.grossProfit - summary.totalExpenses);
  });

  it('records transaction with QRIS payment method', async () => {
    const storage = new JsonStorage(testStorageDir);
    const productRepo = new JsonProductRepository(storage);
    const txRepo = new JsonTransactionRepository(storage);
    const txUseCases = new TransactionUseCases(txRepo, productRepo);

    const prod = await productRepo.create({
      name: 'Kopi Hitam',
      category: 'Minuman',
      costPrice: 2000,
      sellingPrice: 5000
    });

    const tx = await txUseCases.recordSale({
      paymentMethod: 'QRIS',
      items: [{ productId: prod.id, quantity: 1 }]
    });

    assert.strictEqual(tx.paymentMethod, 'QRIS');
    assert.strictEqual(tx.totalRevenue, 5000);
  });
});
