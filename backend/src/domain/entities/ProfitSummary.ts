export interface ProfitSummary {
  period: string;
  totalRevenue: number;
  totalCogs: number;
  grossProfit: number;
  totalExpenses: number;
  netProfit: number;
  grossMarginPercent: number;
  netMarginPercent: number;
  totalCustomers: number;
}

export interface ChartDataPoint {
  date: string;
  revenue: number;
  grossProfit: number;
  expenses: number;
  netProfit: number;
  customerCount: number;
}
