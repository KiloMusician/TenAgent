import { Product, CreateProductDTO, UpdateProductDTO } from '../entities/Product';

export interface IProductRepository {
  findAll(category?: string, search?: string): Promise<Product[]>;
  findById(id: string): Promise<Product | null>;
  create(dto: CreateProductDTO): Promise<Product>;
  update(id: string, dto: UpdateProductDTO): Promise<Product | null>;
  delete(id: string): Promise<boolean>;
}
