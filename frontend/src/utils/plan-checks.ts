import type { JsonMap } from '../types/governed';

export function hasProviderOperation(ops: JsonMap[], provider: string): boolean {
  return ops.some((op) => {
    const inputs = op.inputs;
    if (typeof inputs === 'object' && inputs !== null && 'provider' in inputs) {
      return (inputs as JsonMap).provider === provider;
    }
    return false;
  });
}

export function findBranchValue(ops: JsonMap[]): string | undefined {
  for (const op of ops) {
    const inputs = op.inputs;
    if (typeof inputs === 'object' && inputs !== null) {
      const branch = (inputs as JsonMap).branch;
      if (typeof branch === 'string' && branch.trim()) return branch;
      const defaultBranch = (inputs as JsonMap).default_branch;
      if (typeof defaultBranch === 'string' && defaultBranch.trim()) return defaultBranch;
      const productionBranch = (inputs as JsonMap).production_branch;
      if (typeof productionBranch === 'string' && productionBranch.trim()) return productionBranch;
    }
  }
  return undefined;
}
