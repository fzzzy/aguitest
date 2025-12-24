import type { Plugin } from 'vite'
import fs from 'node:fs'
import { transformWithEsbuild } from 'vite'

export function sfcPlugin(): Plugin {
  return {
    name: 'vite-plugin-sfc',
    enforce: 'pre',

    transform(code: string, id: string) {
      // Transform registerComponents('glob') -> registerComponents(import.meta.glob('glob', { eager: true }))
      if (id.endsWith('.ts') || id.endsWith('.js')) {
        const transformed = code.replace(
          /registerComponents\s*\(\s*(['"`])([^'"`]+)\1\s*\)/g,
          (_, quote, glob) => `registerComponents(import.meta.glob(${quote}${glob}${quote}, { eager: true }))`
        )
        if (transformed !== code) {
          return transformed
        }
      }
      return null
    },

    async load(id: string) {
      if (!id.endsWith('.sfc.html')) {
        return null
      }

      const code = fs.readFileSync(id, 'utf-8')

      // Parse template and script from SFC
      const templateMatch = code.match(/<template>([\s\S]*?)<\/template>/)
      const scriptMatch = code.match(/<script[^>]*>([\s\S]*?)<\/script>/)

      if (!templateMatch) {
        throw new Error(`${id}: SFC must contain a <template> block`)
      }

      const templateContent = templateMatch[1].trim()
      const scriptContent = scriptMatch ? scriptMatch[1].trim() : 'export default defineComponent(template);'

      // Generate the transformed module
      const tsCode = `
const template = document.createElement('template');
template.innerHTML = ${JSON.stringify(templateContent)};

function defineComponent(template: HTMLTemplateElement): CustomElementConstructor {
  return class extends HTMLElement {
    connectedCallback() {
      this.attachShadow({ mode: 'open' });
      this.shadowRoot!.appendChild(template.content.cloneNode(true));
    }
  };
}

${scriptContent}
`
      // Transform TypeScript to JavaScript
      const result = await transformWithEsbuild(tsCode, id + '.ts', {
        loader: 'ts',
        target: 'es2022'
      })

      return result.code
    }
  }
}
