import { Request, Response } from 'express';
import { ExpenseUseCases } from '../../domain/usecases/ExpenseUseCases';

export class ExpenseController {
  constructor(private readonly expenseUseCases: ExpenseUseCases) {}

  async listExpenses(req: Request, res: Response): Promise<Response> {
    try {
      const startDate = req.query.startDate as string | undefined;
      const endDate = req.query.endDate as string | undefined;
      const expenses = await this.expenseUseCases.listExpenses(startDate, endDate);
      return res.status(200).json(expenses);
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }

  async createExpense(req: Request, res: Response): Promise<Response> {
    try {
      const { expenseDate, category, amount, notes } = req.body;
      if (!category || amount === undefined) {
        return res.status(400).json({ error: 'Category and amount are required' });
      }
      const expense = await this.expenseUseCases.recordExpense({
        expenseDate,
        category,
        amount: Number(amount),
        notes
      });
      return res.status(201).json(expense);
    } catch (error: any) {
      return res.status(400).json({ error: error.message });
    }
  }

  async deleteExpense(req: Request, res: Response): Promise<Response> {
    try {
      const deleted = await this.expenseUseCases.deleteExpense(req.params.id);
      if (!deleted) {
        return res.status(404).json({ error: 'Expense not found' });
      }
      return res.status(204).send();
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }
}
