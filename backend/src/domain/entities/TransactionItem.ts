export interface TransactionItem {
  id: string;
  transactionId: string;
  productId: string;
  productName: string;
  quantity: number;
  costPrice: number;
  sellingPrice: number;
  subtotalRevenue: number;
  subtotalCogs: number;
  subtotalProfit: number;
  createdAt: string;
}

export interface CreateTransactionItemDTO {
  productId: string;
  quantity: number;
}
