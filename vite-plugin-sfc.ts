import type { Plugin } from 'vite'
import fs from 'node:fs'
import path from 'node:path'
import { transformWithOxc } from 'vite'

export function sfcPlugin(): Plugin {
  return {
    name: 'vite-plugin-sfc',
    enforce: 'pre',

    handleHotUpdate({ file, server }) {
      if (file.endsWith('.sfc.html')) {
        server.ws.send({ type: 'full-reload' })
        return []
      }
    },

    async resolveId(source: string, importer: string | undefined) {
      if (source.endsWith('.sfc.html')) {
        // Let Vite resolve the absolute path first
        const resolution = await this.resolve(source, importer, {
          skipSelf: true,
        })
        if (resolution) {
          // Prefix with \0 to tell Rolldown this is a virtual module so it doesn't look for it on disk
          return '\0' + resolution.id + '?sfc'
        }
      }
      return null
    },

    async load(id: string) {
      if (!id.startsWith('\0') || !id.endsWith('.sfc.html?sfc')) {
        return null
      }

      // Remove \0 and ?sfc to get the real file path
      const filePath = id.slice(1).replace(/\?sfc$/, '')
      this.addWatchFile(filePath)
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
