import { Request, Response } from 'express';
import { ProductUseCases } from '../../domain/usecases/ProductUseCases';

export class ProductController {
  constructor(private readonly productUseCases: ProductUseCases) {}

  async listProducts(req: Request, res: Response): Promise<Response> {
    try {
      const category = req.query.category as string | undefined;
      const search = req.query.search as string | undefined;
      const products = await this.productUseCases.listProducts(category, search);
      return res.status(200).json(products);
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }

  async getProduct(req: Request, res: Response): Promise<Response> {
    try {
      const product = await this.productUseCases.getProductById(req.params.id);
      if (!product) {
        return res.status(404).json({ error: 'Product not found' });
      }
      return res.status(200).json(product);
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }

  async createProduct(req: Request, res: Response): Promise<Response> {
    try {
      const { name, category, costPrice, sellingPrice } = req.body;
      if (!name || costPrice === undefined || sellingPrice === undefined) {
        return res.status(400).json({ error: 'Name, costPrice, and sellingPrice are required' });
      }
      const product = await this.productUseCases.createProduct({
        name,
        category,
        costPrice: Number(costPrice),
        sellingPrice: Number(sellingPrice)
      });
      return res.status(201).json(product);
    } catch (error: any) {
      return res.status(400).json({ error: error.message });
    }
  }

  async updateProduct(req: Request, res: Response): Promise<Response> {
    try {
      const updated = await this.productUseCases.updateProduct(req.params.id, req.body);
      if (!updated) {
        return res.status(404).json({ error: 'Product not found' });
      }
      return res.status(200).json(updated);
    } catch (error: any) {
      return res.status(400).json({ error: error.message });
    }
  }

  async deleteProduct(req: Request, res: Response): Promise<Response> {
    try {
      const deleted = await this.productUseCases.deleteProduct(req.params.id);
      if (!deleted) {
        return res.status(404).json({ error: 'Product not found' });
      }
      return res.status(204).send();
    } catch (error: any) {
      return res.status(500).json({ error: error.message });
    }
  }
}
