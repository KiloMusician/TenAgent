import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { IProductRepository } from '../../domain/repositories/IProductRepository';
import { ITransactionRepository } from '../../domain/repositories/ITransactionRepository';
import { IExpenseRepository } from '../../domain/repositories/IExpenseRepository';
import { IAnalyticsRepository } from '../../domain/repositories/IAnalyticsRepository';
import { Product, CreateProductDTO, UpdateProductDTO, calculateProductMargin } from '../../domain/entities/Product';
import { TransactionHeader, TransactionDetail, CreateTransactionDTO } from '../../domain/entities/Transaction';
import { TransactionItem } from '../../domain/entities/TransactionItem';
import { Expense, CreateExpenseDTO } from '../../domain/entities/Expense';
import { ProfitSummary, ChartDataPoint } from '../../domain/entities/ProfitSummary';

export interface StoreData {
  products: Product[];
  transactions: TransactionDetail[];
  expenses: Expense[];
}

export class JsonStorage {
  private readonly filePath: string;
  private data: StoreData;

  constructor(storageDir?: string) {
    const dir = storageDir || path.join(__dirname, '../../../storage');
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    this.filePath = path.join(dir, 'warung_store.json');
    this.data = this.loadData();
  }

  getData(): StoreData {
    return this.data;
  }

  saveData(): void {
    fs.writeFileSync(this.filePath, JSON.stringify(this.data, null, 2), 'utf-8');
  }

  private loadData(): StoreData {
    if (fs.existsSync(this.filePath)) {
      try {
        const content = fs.readFileSync(this.filePath, 'utf-8');
        return JSON.parse(content);
      } catch {
        return this.initializeSeedData();
      }
    }
    const initial = this.initializeSeedData();
    fs.writeFileSync(this.filePath, JSON.stringify(initial, null, 2), 'utf-8');
    return initial;
  }

  private initializeSeedData(): StoreData {
    const now = new Date().toISOString();
    const today = now.split('T')[0];

    const sampleProducts: Product[] = [
      {
        id: crypto.randomUUID(),
        name: 'Es Teh Manis',
        category: 'Minuman',
        costPrice: 1500,
        sellingPrice: 4000,
        ...calculateProductMargin(1500, 4000),
        isActive: true,
        createdAt: now,
        updatedAt: now
      },
      {
        id: crypto.randomUUID(),
        name: 'Kopi Tubruk',
        category: 'Minuman',
        costPrice: 2000,
        sellingPrice: 5000,
        ...calculateProductMargin(2000, 5000),
        isActive: true,
        createdAt: now,
        updatedAt: now
      },
      {
        id: crypto.randomUUID(),
        name: 'Nasi Goreng Spesial',
        category: 'Makanan',
        costPrice: 9000,
        sellingPrice: 15000,
        ...calculateProductMargin(9000, 15000),
        isActive: true,
        createdAt: now,
        updatedAt: now
      },
      {
        id: crypto.randomUUID(),
        name: 'Mie Instan Telur',
        category: 'Makanan',
        costPrice: 6000,
        sellingPrice: 10000,
        ...calculateProductMargin(6000, 10000),
        isActive: true,
        createdAt: now,
        updatedAt: now
      },
      {
        id: crypto.randomUUID(),
        name: 'Gorengan Tempe / Tahu',
        category: 'Camilan',
        costPrice: 600,
        sellingPrice: 1200,
        ...calculateProductMargin(600, 1200),
        isActive: true,
        createdAt: now,
        updatedAt: now
      }
    ];

    const sampleExpenses: Expense[] = [
      {
        id: crypto.randomUUID(),
        expenseDate: today,
        category: 'Kantong & Kemasan',
        amount: 25000,
        notes: 'Plastik kresek dan sedotan',
        createdAt: now,
        updatedAt: now
      },
      {
        id: crypto.randomUUID(),
        expenseDate: today,
        category: 'Gas & Es Batu',
        amount: 35000,
        notes: 'Isi ulang gas LPG 3kg dan es balok',
        createdAt: now,
        updatedAt: now
      }
    ];

    return {
      products: sampleProducts,
      transactions: [],
      expenses: sampleExpenses
    };
  }
}

export class JsonProductRepository implements IProductRepository {
  constructor(private readonly storage: JsonStorage) {}

  async findAll(category?: string, search?: string): Promise<Product[]> {
    const data = this.storage.getData();
    return data.products.filter(p => {
      if (!p.isActive) return false;
      if (category && p.category.toLowerCase() !== category.toLowerCase()) return false;
      if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }

  async findById(id: string): Promise<Product | null> {
    const data = this.storage.getData();
    return data.products.find(p => p.id === id) || null;
  }

  async create(dto: CreateProductDTO): Promise<Product> {
    const data = this.storage.getData();
    const now = new Date().toISOString();
    const margin = calculateProductMargin(dto.costPrice, dto.sellingPrice);
    const newProduct: Product = {
      id: crypto.randomUUID(),
      name: dto.name,
      category: dto.category || 'Umum',
      costPrice: dto.costPrice,
      sellingPrice: dto.sellingPrice,
      unitMargin: margin.unitMargin,
      marginPercentage: margin.marginPercentage,
      isActive: true,
      createdAt: now,
      updatedAt: now
    };
    data.products.push(newProduct);
    this.storage.saveData();
    return newProduct;
  }

  async update(id: string, dto: UpdateProductDTO): Promise<Product | null> {
    const data = this.storage.getData();
    const index = data.products.findIndex(p => p.id === id);
    if (index === -1) return null;

    const existing = data.products[index];
    const costPrice = dto.costPrice !== undefined ? dto.costPrice : existing.costPrice;
    const sellingPrice = dto.sellingPrice !== undefined ? dto.sellingPrice : existing.sellingPrice;
    const margin = calculateProductMargin(costPrice, sellingPrice);

    const updated: Product = {
      ...existing,
      name: dto.name !== undefined ? dto.name : existing.name,
      category: dto.category !== undefined ? dto.category : existing.category,
      costPrice,
      sellingPrice,
      unitMargin: margin.unitMargin,
      marginPercentage: margin.marginPercentage,
      isActive: dto.isActive !== undefined ? dto.isActive : existing.isActive,
      updatedAt: new Date().toISOString()
    };

    data.products[index] = updated;
    this.storage.saveData();
    return updated;
  }

  async delete(id: string): Promise<boolean> {
    const data = this.storage.getData();
    const index = data.products.findIndex(p => p.id === id);
    if (index === -1) return false;
    data.products[index].isActive = false;
    data.products[index].updatedAt = new Date().toISOString();
    this.storage.saveData();
    return true;
  }
}

export class JsonTransactionRepository implements ITransactionRepository {
  constructor(private readonly storage: JsonStorage) {}

  async findAll(startDate?: string, endDate?: string): Promise<TransactionHeader[]> {
    const data = this.storage.getData();
    return data.transactions
      .filter(t => {
        const txDate = t.createdAt.split('T')[0];
        if (startDate && txDate < startDate) return false;
        if (endDate && txDate > endDate) return false;
        return true;
      })
      .map(({ items, ...header }) => header);
  }

  async findById(id: string): Promise<TransactionDetail | null> {
    const data = this.storage.getData();
    return data.transactions.find(t => t.id === id) || null;
  }

  async create(dto: CreateTransactionDTO): Promise<TransactionDetail> {
    const data = this.storage.getData();
    const now = new Date().toISOString();
    const invoiceNumber = `INV-${Date.now().toString().slice(-6)}`;
    const txId = crypto.randomUUID();

    let totalRevenue = 0;
    let totalCogs = 0;

    const items: TransactionItem[] = dto.items.map(reqItem => {
      const product = data.products.find(p => p.id === reqItem.productId);
      if (!product) {
        throw new Error(`Product not found: ${reqItem.productId}`);
      }
      const subtotalRevenue = product.sellingPrice * reqItem.quantity;
      const subtotalCogs = product.costPrice * reqItem.quantity;
      const subtotalProfit = subtotalRevenue - subtotalCogs;

      totalRevenue += subtotalRevenue;
      totalCogs += subtotalCogs;

      return {
        id: crypto.randomUUID(),
        transactionId: txId,
        productId: product.id,
        productName: product.name,
        quantity: reqItem.quantity,
        costPrice: product.costPrice,
        sellingPrice: product.sellingPrice,
        subtotalRevenue,
        subtotalCogs,
        subtotalProfit,
        createdAt: now
      };
    });

    const grossProfit = totalRevenue - totalCogs;

    const newTx: TransactionDetail = {
      id: txId,
      invoiceNumber,
      totalRevenue,
      totalCogs,
      grossProfit,
      paymentMethod: dto.paymentMethod || 'CASH',
      notes: dto.notes,
      createdAt: now,
      items
    };

    data.transactions.unshift(newTx);
    this.storage.saveData();
    return newTx;
  }
}

export class JsonExpenseRepository implements IExpenseRepository {
  constructor(private readonly storage: JsonStorage) {}

  async findAll(startDate?: string, endDate?: string): Promise<Expense[]> {
    const data = this.storage.getData();
    return data.expenses.filter(e => {
      if (startDate && e.expenseDate < startDate) return false;
      if (endDate && e.expenseDate > endDate) return false;
      return true;
    }).sort((a, b) => b.expenseDate.localeCompare(a.expenseDate));
  }

  async findById(id: string): Promise<Expense | null> {
    const data = this.storage.getData();
    return data.expenses.find(e => e.id === id) || null;
  }

  async create(dto: CreateExpenseDTO): Promise<Expense> {
    const data = this.storage.getData();
    const now = new Date().toISOString();
    const newExpense: Expense = {
      id: crypto.randomUUID(),
      expenseDate: dto.expenseDate || now.split('T')[0],
      category: dto.category,
      amount: dto.amount,
      notes: dto.notes,
      createdAt: now,
      updatedAt: now
    };
    data.expenses.unshift(newExpense);
    this.storage.saveData();
    return newExpense;
  }

  async delete(id: string): Promise<boolean> {
    const data = this.storage.getData();
    const index = data.expenses.findIndex(e => e.id === id);
    if (index === -1) return false;
    data.expenses.splice(index, 1);
    this.storage.saveData();
    return true;
  }
}

export class JsonAnalyticsRepository implements IAnalyticsRepository {
  constructor(private readonly storage: JsonStorage) {}

  async getSummary(period: string = 'today'): Promise<ProfitSummary> {
    const data = this.storage.getData();
    const dateRange = this.computePeriodDates(period);
    const transactions = data.transactions.filter(t => {
      const txDate = t.createdAt.split('T')[0];
      return (!dateRange.start || txDate >= dateRange.start) && (!dateRange.end || txDate <= dateRange.end);
    });

    const expenses = data.expenses.filter(e => {
      return (!dateRange.start || e.expenseDate >= dateRange.start) && (!dateRange.end || e.expenseDate <= dateRange.end);
    });

    const totalRevenue = transactions.reduce((acc, t) => acc + t.totalRevenue, 0);
    const totalCogs = transactions.reduce((acc, t) => acc + t.totalCogs, 0);
    const grossProfit = totalRevenue - totalCogs;
    const totalExpenses = expenses.reduce((acc, e) => acc + e.amount, 0);
    const netProfit = grossProfit - totalExpenses;

    const grossMarginPercent = totalRevenue > 0 ? Math.round((grossProfit / totalRevenue) * 1000) / 10 : 0;
    const netMarginPercent = totalRevenue > 0 ? Math.round((netProfit / totalRevenue) * 1000) / 10 : 0;
    const totalCustomers = transactions.length;

    return {
      period,
      totalRevenue,
      totalCogs,
      grossProfit,
      totalExpenses,
      netProfit,
      grossMarginPercent,
      netMarginPercent,
      totalCustomers
    };
  }

  async getChartData(period: string = '7d'): Promise<ChartDataPoint[]> {
    const data = this.storage.getData();
    let daysCount = 7;
    if (period === '30d') daysCount = 30;
    else if (period === '7d') daysCount = 7;
    else if (period === '3d') daysCount = 3;
    else if (period === 'today') daysCount = 1;

    const points: ChartDataPoint[] = [];
    const now = new Date();

    for (let i = daysCount - 1; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const dateStr = d.toISOString().split('T')[0];

      const dayTransactions = data.transactions.filter(t => t.createdAt.split('T')[0] === dateStr);
      const dayExpenses = data.expenses.filter(e => e.expenseDate === dateStr);

      const revenue = dayTransactions.reduce((acc, t) => acc + t.totalRevenue, 0);
      const cogs = dayTransactions.reduce((acc, t) => acc + t.totalCogs, 0);
      const grossProfit = revenue - cogs;
      const expenses = dayExpenses.reduce((acc, e) => acc + e.amount, 0);
      const netProfit = grossProfit - expenses;
      const customerCount = dayTransactions.length;

      points.push({
        date: dateStr,
        revenue,
        grossProfit,
        expenses,
        netProfit,
        customerCount
      });
    }

    return points;
  }

  private computePeriodDates(period: string): { start?: string; end?: string } {
    const now = new Date();
    const isoDate = now.toISOString().split('T')[0];
    const localYear = now.getFullYear();
    const localMonth = String(now.getMonth() + 1).padStart(2, '0');
    const localDay = String(now.getDate()).padStart(2, '0');
    const localDate = `${localYear}-${localMonth}-${localDay}`;
    const todayStr = localDate > isoDate ? localDate : isoDate;

    if (period === 'today') {
      const minToday = localDate < isoDate ? localDate : isoDate;
      return { start: minToday, end: todayStr };
    }
    if (period === '3d') {
      const d = new Date(now);
      d.setDate(d.getDate() - 2);
      const minDate = d.toISOString().split('T')[0];
      return { start: minDate, end: todayStr };
    }
    if (period === '7d') {
      const d = new Date(now);
      d.setDate(d.getDate() - 6);
      const minDate = d.toISOString().split('T')[0];
      return { start: minDate, end: todayStr };
    }
    if (period === '30d') {
      const d = new Date(now);
      d.setDate(d.getDate() - 29);
      const minDate = d.toISOString().split('T')[0];
      return { start: minDate, end: todayStr };
    }
    return {};
  }
}
