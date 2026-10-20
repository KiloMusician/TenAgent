import { Router } from 'express';
import { ProductController } from '../controllers/ProductController';
import { TransactionController } from '../controllers/TransactionController';
import { ExpenseController } from '../controllers/ExpenseController';
import { AnalyticsController } from '../controllers/AnalyticsController';

export function createApiRouter(
  productController: ProductController,
  transactionController: TransactionController,
  expenseController: ExpenseController,
  analyticsController: AnalyticsController
): Router {
  const router = Router();

  // Products
  router.get('/products', (req, res) => productController.listProducts(req, res));
  router.get('/products/:id', (req, res) => productController.getProduct(req, res));
  router.post('/products', (req, res) => productController.createProduct(req, res));
  router.put('/products/:id', (req, res) => productController.updateProduct(req, res));
  router.delete('/products/:id', (req, res) => productController.deleteProduct(req, res));

  // Transactions
  router.get('/transactions', (req, res) => transactionController.listTransactions(req, res));
  router.get('/transactions/:id', (req, res) => transactionController.getTransaction(req, res));
  router.post('/transactions', (req, res) => transactionController.createTransaction(req, res));

  // Expenses
  router.get('/expenses', (req, res) => expenseController.listExpenses(req, res));
  router.post('/expenses', (req, res) => expenseController.createExpense(req, res));
  router.delete('/expenses/:id', (req, res) => expenseController.deleteExpense(req, res));

  // Analytics & Profit
  router.get('/analytics/summary', (req, res) => analyticsController.getSummary(req, res));
  router.get('/analytics/charts', (req, res) => analyticsController.getChartData(req, res));

  return router;
}
