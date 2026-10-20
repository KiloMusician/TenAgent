import { IProductRepository } from '../repositories/IProductRepository';
import { Product, CreateProductDTO, UpdateProductDTO } from '../entities/Product';

export class ProductUseCases {
  constructor(private readonly productRepo: IProductRepository) {}

  async listProducts(category?: string, search?: string): Promise<Product[]> {
    return this.productRepo.findAll(category, search);
  }

  async getProductById(id: string): Promise<Product | null> {
    return this.productRepo.findById(id);
  }

  async createProduct(dto: CreateProductDTO): Promise<Product> {
    if (!dto.name || dto.name.trim() === '') {
      throw new Error('Product name is required');
    }
    if (dto.costPrice === undefined || dto.costPrice === null || typeof dto.costPrice !== 'number' || isNaN(dto.costPrice) || dto.costPrice < 0) {
      throw new Error('Cost price must be non-negative');
    }
    if (dto.sellingPrice === undefined || dto.sellingPrice === null || typeof dto.sellingPrice !== 'number' || isNaN(dto.sellingPrice) || dto.sellingPrice < 0) {
      throw new Error('Selling price must be non-negative');
    }

    return this.productRepo.create({
      ...dto,
      name: dto.name.trim(),
      category: dto.category?.trim() || 'Umum',
    });
  }

  async updateProduct(id: string, dto: UpdateProductDTO): Promise<Product | null> {
    if (dto.costPrice !== undefined && (dto.costPrice === null || typeof dto.costPrice !== 'number' || isNaN(dto.costPrice) || dto.costPrice < 0)) {
      throw new Error('Cost price must be a valid non-negative number');
    }
    if (dto.sellingPrice !== undefined && (dto.sellingPrice === null || typeof dto.sellingPrice !== 'number' || isNaN(dto.sellingPrice) || dto.sellingPrice < 0)) {
      throw new Error('Selling price must be a valid non-negative number');
    }
    return this.productRepo.update(id, dto);
  }

  async deleteProduct(id: string): Promise<boolean> {
    return this.productRepo.delete(id);
  }
}
