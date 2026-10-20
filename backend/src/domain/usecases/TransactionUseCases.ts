import { ITransactionRepository } from '../repositories/ITransactionRepository';
import { IProductRepository } from '../repositories/IProductRepository';
import { TransactionHeader, TransactionDetail, CreateTransactionDTO } from '../entities/Transaction';

export class TransactionUseCases {
  constructor(
    private readonly transactionRepo: ITransactionRepository,
    private readonly productRepo: IProductRepository
  ) {}

  async listTransactions(startDate?: string, endDate?: string): Promise<TransactionHeader[]> {
    return this.transactionRepo.findAll(startDate, endDate);
  }

  async getTransactionById(id: string): Promise<TransactionDetail | null> {
    return this.transactionRepo.findById(id);
  }

  async recordSale(dto: CreateTransactionDTO): Promise<TransactionDetail> {
    if (!dto.items || dto.items.length === 0) {
      throw new Error('Transaction must contain at least one item');
    }

    for (const item of dto.items) {
      if (!item.quantity || typeof item.quantity !== 'number' || isNaN(item.quantity) || item.quantity <= 0) {
        throw new Error('Item quantity must be greater than zero');
      }
      const product = await this.productRepo.findById(item.productId);
      if (!product) {
        throw new Error(`Product with ID ${item.productId} was not found`);
      }
    }

    return this.transactionRepo.create(dto);
  }
}
