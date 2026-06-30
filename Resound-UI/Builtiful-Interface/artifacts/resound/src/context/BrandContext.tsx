import { createContext, useContext, useState, type ReactNode } from "react";
import { useListBrands } from "@workspace/api-client-react";
import { toBrandView, type BrandView } from "@/api/viewModels";

interface BrandContextValue {
  activeBrand: BrandView;
  brands: BrandView[];
  isLoading: boolean;
  isError: boolean;
  setActiveBrand: (brand: BrandView | string) => void;
}

const BrandContext = createContext<BrandContextValue | null>(null);

const fallbackBrand: BrandView = {
  id: "loading",
  numericId: 0,
  name: "Loading",
  tagline: "Connecting to Resound memory",
  primaryContact: "operator",
  sourcesActive: [],
  lastIngested: null,
  ownerOptions: [],
};

export function BrandProvider({ children }: { children: ReactNode }) {
  const { data, isLoading, isError } = useListBrands();
  const brands = (data ?? []).map(toBrandView);
  const [activeBrandId, setActiveBrandId] = useState<string | null>(null);
  const activeBrand = brands.find((brand) => brand.id === activeBrandId) ?? brands[0] ?? fallbackBrand;

  const setActiveBrand = (brand: BrandView | string) => {
    setActiveBrandId(typeof brand === "string" ? brand : brand.id);
  };

  return (
    <BrandContext.Provider value={{ activeBrand, brands, isLoading, isError, setActiveBrand }}>
      {children}
    </BrandContext.Provider>
  );
}

export function useBrand() {
  const ctx = useContext(BrandContext);
  if (!ctx) throw new Error("useBrand must be used within BrandProvider");
  return ctx;
}
