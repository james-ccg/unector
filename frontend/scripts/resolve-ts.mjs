/**
 * Lets Node run the game's TypeScript sources directly.
 *
 * Node strips types on its own, but it will not guess file extensions the
 * way a bundler does, and the game modules import each other as './route'
 * rather than './route.ts'. Rewriting those imports just to suit a test
 * script would be the tail wagging the dog, so this hook appends the
 * extension when a relative specifier does not resolve on its own.
 *
 * Registered by scripts/register.mjs, which physics-check.ts is run with.
 */
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context)
  } catch (err) {
    if (specifier.startsWith('.')) return nextResolve(specifier + '.ts', context)
    throw err
  }
}
