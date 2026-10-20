import { TransactionItem } from './TransactionItem';

export interface TransactionHeader {
  id: string;
  invoiceNumber: string;
  totalRevenue: number;
  totalCogs: number;
  grossProfit: number;
  paymentMethod: string;
  notes?: string;
  createdAt: string;
}

export interface TransactionDetail extends TransactionHeader {
  items: TransactionItem[];
}

export interface CreateTransactionDTO {
  paymentMethod?: string;
  notes?: string;
  items: {
    productId: string;
    quantity: number;
  }[];
}
