import { IAnalyticsRepository } from '../repositories/IAnalyticsRepository';
import { ProfitSummary, ChartDataPoint } from '../entities/ProfitSummary';

export class AnalyticsUseCases {
  constructor(private readonly analyticsRepo: IAnalyticsRepository) {}

  async getSummary(period?: string): Promise<ProfitSummary> {
    return this.analyticsRepo.getSummary(period);
  }

  async getChartData(period?: string): Promise<ChartDataPoint[]> {
    return this.analyticsRepo.getChartData(period);
  }
}
