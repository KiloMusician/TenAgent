import { ProfitSummary, ChartDataPoint } from '../entities/ProfitSummary';

export interface IAnalyticsRepository {
  getSummary(period?: string): Promise<ProfitSummary>;
  getChartData(period?: string): Promise<ChartDataPoint[]>;
}
