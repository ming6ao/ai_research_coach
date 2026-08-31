// Minimal ESM resolver so Node's type-stripping test runner can import
// extensionless relative paths used by the app source (e.g. "../api/client").
import { existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const EXTENSIONS = ['.ts', '.tsx', '.js'];

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith('./') || specifier.startsWith('../')) {
    const parentDir = dirname(fileURLToPath(context.parentURL));
    const candidate = join(parentDir, specifier);
    const hasExt = /\.[cm]?[jt]sx?$/.test(specifier);
    if (!hasExt) {
      for (const ext of EXTENSIONS) {
        if (existsSync(candidate + ext)) {
          return {
            url: pathToFileURL(candidate + ext).href,
            shortCircuit: true,
          };
        }
      }
      if (existsSync(join(candidate, 'index.ts'))) {
        return {
          url: pathToFileURL(join(candidate, 'index.ts')).href,
          shortCircuit: true,
        };
      }
    }
  }
  return nextResolve(specifier, context);
}