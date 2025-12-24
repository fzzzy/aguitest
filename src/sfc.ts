type ComponentModule = { default: CustomElementConstructor }
type GlobResult = Record<string, ComponentModule>

/**
 * Register SFC components from a glob pattern.
 * Tag names are derived from filenames (e.g., chat-header.sfc -> <chat-header>)
 *
 * Usage:
 *   registerComponents('./components/*.sfc')
 *   registerComponents('./components/chat-header.sfc')  // single component
 */
export function registerComponents(glob: string): void
export function registerComponents(modules: GlobResult): void
export function registerComponents(input: string | GlobResult) {
  // String form is transformed to glob result at compile time
  const modules = input as GlobResult
  for (const [path, module] of Object.entries(modules)) {
    // Extract filename without extension: './components/chat-header.sfc' -> 'chat-header'
    const filename = path.split('/').pop()!
    const tagName = filename.replace(/\.sfc$/, '')

    customElements.define(tagName, module.default)
  }
}
