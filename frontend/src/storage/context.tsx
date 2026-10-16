import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";

import { extensions } from "@/extensions";
import type { StorageAdapter } from "@/storage/adapter";
import { ApiStorageAdapter } from "@/storage/adapter";
import { setStorageAdapter } from "@/stores/plan_store";

interface StorageContextValue {
  adapter: StorageAdapter;
  /** True for a sign-in extension's read-only sample, whose changes ask the visitor to sign in. */
  sample: boolean;
}

const StorageContext = createContext<StorageContextValue | null>(null);

export function StorageProvider({
  sample = false,
  children,
}: {
  sample?: boolean;
  children: ReactNode;
}) {
  const adapter = useMemo<StorageAdapter>(() => {
    const preview = extensions.session?.sample;
    const a = sample && preview ? preview.createAdapter() : new ApiStorageAdapter();
    setStorageAdapter(a);
    preview?.setActive(sample);
    return a;
  }, [sample]);

  const value = useMemo(() => ({ adapter, sample }), [adapter, sample]);

  return <StorageContext.Provider value={value}>{children}</StorageContext.Provider>;
}

export function useStorage(): StorageContextValue {
  const ctx = useContext(StorageContext);
  if (!ctx) {
    throw new Error("useStorage must be used within a StorageProvider");
  }
  return ctx;
}
