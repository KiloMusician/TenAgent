export interface Expense {
  id: string;
  expenseDate: string;
  category: string;
  amount: number;
  notes?: string;
  createdAt: string;
  updatedAt: string;
}

export interface CreateExpenseDTO {
  expenseDate?: string;
  category: string;
  amount: number;
  notes?: string;
}
