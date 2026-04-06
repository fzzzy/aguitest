import type { Plugin } from 'vite'
import fs from 'node:fs'
import path from 'node:path'
import { transformWithOxc } from 'vite'

export function sfcPlugin(): Plugin {
  return {
    name: 'vite-plugin-sfc',
    enforce: 'pre',

    resolveId(source: string, importer: string | undefined) {
      if (source.endsWith('.sfc.html') && importer) {
        const dir = path.dirname(importer.replace(/\?.*$/, ''))
        const resolved = path.resolve(dir, source)
        return resolved + '?sfc'
      }
    },

    async load(id: string) {
      if (!id.endsWith('.sfc.html?sfc')) {
        return null
      }

      const filePath = id.replace(/\?sfc$/, '')
      const code = fs.readFileSync(filePath, 'utf-8')

      // Parse template and script from SFC
      const templateMatch = code.match(/<template>([\s\S]*?)<\/template>/)
      const scriptMatch = code.match(/<script[^>]*>([\s\S]*?)<\/script>/)

      const hasTemplate = !!templateMatch
      const templateContent = templateMatch ? templateMatch[1].trim() : ''

      // Script is required if no template, otherwise defaults to defineComponent
      if (!hasTemplate && !scriptMatch) {
        throw new Error(`${filePath}: SFC must contain a <template> or <script> block`)
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
      const result = await transformWithOxc(tsCode, filePath + '.ts', {
        loader: 'ts',
        target: 'es2022'
      })

      return result.code
    }
  }
}
