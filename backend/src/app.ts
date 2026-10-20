import express, { Application } from 'express';
import cors from 'cors';
import path from 'path';
import fs from 'fs';
import {
  JsonStorage,
  JsonProductRepository,
  JsonTransactionRepository,
  JsonExpenseRepository,
  JsonAnalyticsRepository
} from './data/repositories/JsonDataRepository';
import { ProductUseCases } from './domain/usecases/ProductUseCases';
import { TransactionUseCases } from './domain/usecases/TransactionUseCases';
import { ExpenseUseCases } from './domain/usecases/ExpenseUseCases';
import { AnalyticsUseCases } from './domain/usecases/AnalyticsUseCases';
import { ProductController } from './presentation/controllers/ProductController';
import { TransactionController } from './presentation/controllers/TransactionController';
import { ExpenseController } from './presentation/controllers/ExpenseController';
import { AnalyticsController } from './presentation/controllers/AnalyticsController';
import { createApiRouter } from './presentation/routes/apiRoutes';

export function createApp(storageDir?: string): Application {
  const app = express();

  app.use(cors());
  app.use(express.json());

  const storage = new JsonStorage(storageDir);
  const productRepo = new JsonProductRepository(storage);
  const transactionRepo = new JsonTransactionRepository(storage);
  const expenseRepo = new JsonExpenseRepository(storage);
  const analyticsRepo = new JsonAnalyticsRepository(storage);

  const productUseCases = new ProductUseCases(productRepo);
  const transactionUseCases = new TransactionUseCases(transactionRepo, productRepo);
  const expenseUseCases = new ExpenseUseCases(expenseRepo);
  const analyticsUseCases = new AnalyticsUseCases(analyticsRepo);

  const productController = new ProductController(productUseCases);
  const transactionController = new TransactionController(transactionUseCases);
  const expenseController = new ExpenseController(expenseUseCases);
  const analyticsController = new AnalyticsController(analyticsUseCases);

  const apiRouter = createApiRouter(
    productController,
    transactionController,
    expenseController,
    analyticsController
  );

  app.get('/api/health', (req, res) => {
    res.status(200).json({ status: 'ok', service: 'warung-pos-backend', timestamp: new Date().toISOString() });
  });

  app.use('/api/v1', apiRouter);

  const staticDir = path.resolve(__dirname, '../../mobile/public');
  if (fs.existsSync(staticDir)) {
    app.use(express.static(staticDir));
    app.get('*', (req, res, next) => {
      if (req.path.startsWith('/api')) return next();
      res.sendFile(path.join(staticDir, 'index.html'));
    });
  }

  return app;
}
