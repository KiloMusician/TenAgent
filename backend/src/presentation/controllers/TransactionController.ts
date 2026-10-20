import { Request, Response } from 'express';
import { TransactionUseCases } from '../../domain/usecases/TransactionUseCases';

export class TransactionController {
  constructor(private readonly transactionUseCases: TransactionUseCases) {}

  async listTransactions(req: Request, res: Response): Promise<Response> {
    try {
      const startDate = req.query.startDate as string | undefined;
      const endDate = req.query.endDate as string | undefined;
      const transactions = await this.transactionUseCases.listTransactions(startDate, endDate);
      return res.status(200).json(transactions);
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }

  async getTransaction(req: Request, res: Response): Promise<Response> {
    try {
      const tx = await this.transactionUseCases.getTransactionById(req.params.id);
      if (!tx) {
        return res.status(404).json({ error: 'Transaction not found' });
      }
      return res.status(200).json(tx);
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }

  async createTransaction(req: Request, res: Response): Promise<Response> {
    try {
      const { items, paymentMethod, notes } = req.body;
      if (!items || !Array.isArray(items) || items.length === 0) {
        return res.status(400).json({ error: 'Items array cannot be empty' });
      }
      const created = await this.transactionUseCases.recordSale({
        items,
        paymentMethod,
        notes
      });
      return res.status(201).json(created);
    } catch (error: any) {
      return res.status(400).json({ error: error.message });
    }
  }
}
