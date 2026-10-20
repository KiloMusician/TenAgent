import { IExpenseRepository } from '../repositories/IExpenseRepository';
import { Expense, CreateExpenseDTO } from '../entities/Expense';

export class ExpenseUseCases {
  constructor(private readonly expenseRepo: IExpenseRepository) {}

  async listExpenses(startDate?: string, endDate?: string): Promise<Expense[]> {
    return this.expenseRepo.findAll(startDate, endDate);
  }

  async recordExpense(dto: CreateExpenseDTO): Promise<Expense> {
    if (!dto.category || dto.category.trim() === '') {
      throw new Error('Expense category is required');
    }
    if (dto.amount === undefined || dto.amount === null || typeof dto.amount !== 'number' || isNaN(dto.amount) || dto.amount <= 0) {
      throw new Error('Expense amount must be a valid number greater than zero');
    }

    return this.expenseRepo.create({
      ...dto,
      category: dto.category.trim(),
      expenseDate: dto.expenseDate || new Date().toISOString().split('T')[0],
      notes: dto.notes?.trim()
    });
  }

  async deleteExpense(id: string): Promise<boolean> {
    return this.expenseRepo.delete(id);
  }
}
