import type { Plugin } from 'vite'
import fs from 'node:fs'
import { transformWithEsbuild } from 'vite'

export function sfcPlugin(): Plugin {
  return {
    name: 'vite-plugin-sfc',
    enforce: 'pre',

    transform(code: string, id: string) {
      // Transform: import Foo from './components/foo.sfc.html'
      // Into: const Foo = (Object.values(import.meta.glob('./components/foo.sfc.html', { eager: true, import: 'default' })) as any)[0]
      if (id.endsWith('.ts') || id.endsWith('.js')) {
        const transformed = code.replace(
          /import\s+(\w+)\s+from\s+(['"`])([^'"`]+\.sfc\.html)\2\s*;?/g,
          (_, name, quote, path) =>
            `const ${name} = (Object.values(import.meta.glob(${quote}${path}${quote}, { eager: true })) as any)[0].default;`
        )
        if (transformed !== code) {
          return transformed
        }
      }
    },

    async load(id: string) {
      if (!id.endsWith('.sfc.html')) {
        return null
      }

      const code = fs.readFileSync(id, 'utf-8')

      // Parse template and script from SFC
      const templateMatch = code.match(/<template>([\s\S]*?)<\/template>/)
      const scriptMatch = code.match(/<script[^>]*>([\s\S]*?)<\/script>/)

      const hasTemplate = !!templateMatch
      const templateContent = templateMatch ? templateMatch[1].trim() : ''

      // Script is required if no template, otherwise defaults to defineComponent
      if (!hasTemplate && !scriptMatch) {
        throw new Error(`${id}: SFC must contain a <template> or <script> block`)
      }

      const scriptContent = scriptMatch ? scriptMatch[1].trim() : 'export default defineComponent(template);'

      // Generate the transformed module
      const templateCode = hasTemplate ? `
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
` : ''

      const tsCode = `${templateCode}
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
