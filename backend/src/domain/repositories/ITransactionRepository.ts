import { TransactionHeader, TransactionDetail, CreateTransactionDTO } from '../entities/Transaction';

export interface ITransactionRepository {
  findAll(startDate?: string, endDate?: string): Promise<TransactionHeader[]>;
  findById(id: string): Promise<TransactionDetail | null>;
  create(dto: CreateTransactionDTO): Promise<TransactionDetail>;
}
