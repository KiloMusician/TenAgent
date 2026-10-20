import { Request, Response } from 'express';
import { AnalyticsUseCases } from '../../domain/usecases/AnalyticsUseCases';

export class AnalyticsController {
  constructor(private readonly analyticsUseCases: AnalyticsUseCases) {}

  async getSummary(req: Request, res: Response): Promise<Response> {
    try {
      const period = (req.query.period as string) || 'today';
      const summary = await this.analyticsUseCases.getSummary(period);
      return res.status(200).json(summary);
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }

  async getChartData(req: Request, res: Response): Promise<Response> {
    try {
      const period = (req.query.period as string) || '7d';
      const chartData = await this.analyticsUseCases.getChartData(period);
      return res.status(200).json(chartData);
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }
}
