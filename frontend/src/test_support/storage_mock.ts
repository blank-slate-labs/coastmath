import type { ReactNode } from "react";

import type { StorageAdapter } from "@/storage/adapter";

/*
 * Module bodies for `vi.mock("@/storage/context", ...)`. Vitest hoists `vi.mock` above
 * the imports, so a test loads this module inside its factory:
 *
 *   vi.mock("@/storage/context", async () =>
 *     (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter));
 *
 * The adapter is read through a getter on every `useStorage()` call, so the factory may
 * name a variable declared after the imports and a test may swap it between cases.
 */

/** What `useStorage()` returns. */
export interface MockStorageValue {
  adapter: StorageAdapter;
  sample: boolean;
}

/** The exports of `@/storage/context` that components use. */
export interface MockStorageContext {
  StorageProvider: (props: { sample?: boolean; children: ReactNode }) => ReactNode;
  useStorage: () => MockStorageValue;
}

export interface StorageMockOptions {
  /** The read-only sample flag; false unless given. */
  sample?: () => boolean;
}

const passThrough = ({ children }: { children: ReactNode }) => children;

/**
 * A storage context with the given adapter. `null` gives no adapter, for components
 * that read only the sample flag.
 */
export function mockStorageContext(
  adapter: (() => unknown) | null,
  { sample = () => false }: StorageMockOptions = {},
): MockStorageContext {
  return {
    StorageProvider: passThrough,
    useStorage: () => ({
      adapter: (adapter ? adapter() : undefined) as StorageAdapter,
      sample: sample(),
    }),
  };
}

/**
 * The real module with `useStorage` replaced: while `adapter()` returns null the real
 * hook runs, so one file can test against a real provider and a stub. Pass the
 * factory's `await importOriginal()`.
 */
export function mockStorageContextOver<T extends { useStorage: () => MockStorageValue }>(
  actual: T,
  adapter: () => unknown,
): T {
  return {
    ...actual,
    useStorage: () => {
      const current = adapter();
      return current === null
        ? actual.useStorage()
        : { adapter: current as StorageAdapter, sample: false };
    },
  };
}
