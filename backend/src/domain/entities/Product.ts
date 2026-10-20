export interface Product {
  id: string;
  name: string;
  category: string;
  costPrice: number;
  sellingPrice: number;
  unitMargin: number;
  marginPercentage: number;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface CreateProductDTO {
  name: string;
  category?: string;
  costPrice: number;
  sellingPrice: number;
}

export interface UpdateProductDTO {
  name?: string;
  category?: string;
  costPrice?: number;
  sellingPrice?: number;
  isActive?: boolean;
}

export function calculateProductMargin(costPrice: number, sellingPrice: number): { unitMargin: number; marginPercentage: number } {
  const unitMargin = Math.round((sellingPrice - costPrice) * 100) / 100;
  const marginPercentage = sellingPrice > 0 
    ? Math.round(((sellingPrice - costPrice) / sellingPrice) * 1000) / 10 
    : 0;
  return { unitMargin, marginPercentage };
}
