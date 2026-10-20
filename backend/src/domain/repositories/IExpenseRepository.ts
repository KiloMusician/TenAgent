import { Expense, CreateExpenseDTO } from '../entities/Expense';

export interface IExpenseRepository {
  findAll(startDate?: string, endDate?: string): Promise<Expense[]>;
  findById(id: string): Promise<Expense | null>;
  create(dto: CreateExpenseDTO): Promise<Expense>;
  delete(id: string): Promise<boolean>;
}
