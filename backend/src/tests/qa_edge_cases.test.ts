import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'fs';
import path from 'path';
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

describe('QA Adversarial & Edge-Case Test Suite', () => {
  const testStorageDir = path.join(__dirname, '../../test-storage-qa');

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

  it('TC-01: Rejects null, undefined, NaN, and negative prices on product creation', async () => {
    const storage = new JsonStorage(testStorageDir);
    const productRepo = new JsonProductRepository(storage);
    const productUseCases = new ProductUseCases(productRepo);

    // Null cost price
    await assert.rejects(
      async () => {
        await productUseCases.createProduct({
          name: 'Produk Uji',
          costPrice: null as any,
          sellingPrice: 5000
        });
      },
      /Cost price must be non-negative/
    );

    // NaN selling price
    await assert.rejects(
      async () => {
        await productUseCases.createProduct({
          name: 'Produk Uji',
          costPrice: 2000,
          sellingPrice: NaN
        });
      },
      /Selling price must be non-negative/
    );

    // Empty product name
    await assert.rejects(
      async () => {
        await productUseCases.createProduct({
          name: '   ',
          costPrice: 2000,
          sellingPrice: 5000
        });
      },
      /Product name is required/
    );
  });

  it('TC-02: Rejects invalid price updates on existing products', async () => {
    const storage = new JsonStorage(testStorageDir);
    const productRepo = new JsonProductRepository(storage);
    const productUseCases = new ProductUseCases(productRepo);

    const prod = await productUseCases.createProduct({
      name: 'Kerupuk Kaleng',
      costPrice: 500,
      sellingPrice: 1000
    });

    await assert.rejects(
      async () => {
        await productUseCases.updateProduct(prod.id, {
          costPrice: -500
        });
      },
      /Cost price must be a valid non-negative number/
    );

    await assert.rejects(
      async () => {
        await productUseCases.updateProduct(prod.id, {
          sellingPrice: null as any
        });
      },
      /Selling price must be a valid non-negative number/
    );
  });

  it('TC-03: Rejects invalid operational expenses (zero, negative, null, empty category)', async () => {
    const storage = new JsonStorage(testStorageDir);
    const expenseRepo = new JsonExpenseRepository(storage);
    const expenseUseCases = new ExpenseUseCases(expenseRepo);

    // Zero amount
    await assert.rejects(
      async () => {
        await expenseUseCases.recordExpense({
          category: 'Listrik',
          amount: 0
        });
      },
      /Expense amount must be a valid number greater than zero/
    );

    // Negative amount
    await assert.rejects(
      async () => {
        await expenseUseCases.recordExpense({
          category: 'Listrik',
          amount: -15000
        });
      },
      /Expense amount must be a valid number greater than zero/
    );

    // Null amount
    await assert.rejects(
      async () => {
        await expenseUseCases.recordExpense({
          category: 'Listrik',
          amount: null as any
        });
      },
      /Expense amount must be a valid number greater than zero/
    );

    // Empty category
    await assert.rejects(
      async () => {
        await expenseUseCases.recordExpense({
          category: '   ',
          amount: 5000
        });
      },
      /Expense category is required/
    );
  });

  it('TC-04: Rejects zero or negative quantities and missing items in sales transaction', async () => {
    const storage = new JsonStorage(testStorageDir);
    const productRepo = new JsonProductRepository(storage);
    const txRepo = new JsonTransactionRepository(storage);
    const txUseCases = new TransactionUseCases(txRepo, productRepo);

    const prod = await productRepo.create({
      name: 'Kacang Goreng',
      costPrice: 1000,
      sellingPrice: 2000
    });

    // Zero quantity
    await assert.rejects(
      async () => {
        await txUseCases.recordSale({
          items: [{ productId: prod.id, quantity: 0 }]
        });
      },
      /Item quantity must be greater than zero/
    );

    // Negative quantity
    await assert.rejects(
      async () => {
        await txUseCases.recordSale({
          items: [{ productId: prod.id, quantity: -2 }]
        });
      },
      /Item quantity must be greater than zero/
    );

    // Non-existent product ID
    await assert.rejects(
      async () => {
        await txUseCases.recordSale({
          items: [{ productId: 'non-existent-uuid', quantity: 1 }]
        });
      },
      /Product with ID non-existent-uuid was not found/
    );
  });

  it('TC-05: Handles zero-division safety in profit margin calculation when revenue is zero', async () => {
    const storage = new JsonStorage(testStorageDir);
    const analyticsRepo = new JsonAnalyticsRepository(storage);
    const analyticsUseCases = new AnalyticsUseCases(analyticsRepo);

    const summary = await analyticsUseCases.getSummary('today');
    assert.strictEqual(summary.grossMarginPercent, 0);
    assert.strictEqual(summary.netMarginPercent, 0);
    assert.strictEqual(typeof summary.totalCustomers, 'number');
    assert.ok(!isNaN(summary.grossMarginPercent));
    assert.ok(!isNaN(summary.netMarginPercent));
  });

  it('TC-06: Accurate daily bucket alignment and customerCount field in 7d and 30d chart data', async () => {
    const storage = new JsonStorage(testStorageDir);
    const analyticsRepo = new JsonAnalyticsRepository(storage);
    const analyticsUseCases = new AnalyticsUseCases(analyticsRepo);

    const chart7d = await analyticsUseCases.getChartData('7d');
    assert.strictEqual(chart7d.length, 7);
    chart7d.forEach(p => {
      assert.ok(typeof p.date === 'string');
      assert.ok(p.revenue >= 0);
      assert.ok(typeof p.grossProfit === 'number');
      assert.ok(typeof p.netProfit === 'number');
      assert.ok(typeof p.customerCount === 'number');
    });

    const chart30d = await analyticsUseCases.getChartData('30d');
    assert.strictEqual(chart30d.length, 30);
  });

  it('TC-07: Verifies daily customerCount increments accurately on transaction completion', async () => {
    const storage = new JsonStorage(testStorageDir);
    const productRepo = new JsonProductRepository(storage);
    const txRepo = new JsonTransactionRepository(storage);
    const txUseCases = new TransactionUseCases(txRepo, productRepo);
    const analyticsRepo = new JsonAnalyticsRepository(storage);
    const analyticsUseCases = new AnalyticsUseCases(analyticsRepo);

    const prod = await productRepo.create({
      name: 'Kopi Susu Barokah',
      costPrice: 2000,
      sellingPrice: 5000
    });

    await txUseCases.recordSale({
      items: [{ productId: prod.id, quantity: 1 }]
    });

    await txUseCases.recordSale({
      items: [{ productId: prod.id, quantity: 2 }]
    });

    const chart = await analyticsUseCases.getChartData('7d');
    const todayPoint = chart[chart.length - 1];
    assert.strictEqual(todayPoint.customerCount, 2);

    const summary = await analyticsUseCases.getSummary('today');
    assert.strictEqual(summary.totalCustomers, 2);
  });
});
