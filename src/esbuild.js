#!/usr/bin/env node

import esbuild from 'esbuild';
import chokidar from 'chokidar';
import { exec } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

(async function main() {
  const isServe = process.argv.includes('--serve');

  const buildConfig = {
    entryPoints: ['./index.ts'],
    bundle: true,
    sourcemap: true,
    outdir: '../dist',
    format: 'esm',
    target: 'es2022',
    logLevel: 'info',
    loader: { '.css': 'css' },  // Bundle CSS to trigger rebuild events (Python also inlines it)
  };

  // Initial build
  await esbuild.build(buildConfig);

  // Generate TypeScript declarations
  exec('node_modules/typescript/bin/tsc', (error, _stdout, stderr) => {
    console.log('Generating type declarations...');
    if (error) {
      console.error(`Error generating type declarations: ${error}\n${stderr}`);
    } else {
      console.log('Type declarations generated.');
    }
    if (stderr) {
      console.error(`TypeScript warnings/errors:\n${stderr}`);
    }
  });

  if (isServe) {
    console.log('Starting watch mode...');
    let ctx = await esbuild.context(buildConfig);

    // Enable watch mode to automatically rebuild on TS file changes
    await ctx.watch();

    // Start esbuild's serve to provide the /esbuild eventsource endpoint
    let { port } = await ctx.serve({ servedir: '../dist', port: 8001 });
    console.log(`esbuild serving on port ${port} (provides /esbuild endpoint at http://localhost:${port}/esbuild)`);

    // Watch for CSS changes and trigger rebuild to notify clients
    const cssPath = path.join(__dirname, '../static');
    console.log(`Watching CSS in: ${cssPath}`);
    let watcher = chokidar.watch(cssPath, {
      ignored: /(^|[\/\\])\../,
      persistent: true,
    });

    watcher.on('change', async (path) => {
      console.log(`CSS file ${path} has been changed`);
      // Trigger a rebuild to send change event to clients
      await ctx.rebuild();
    });

    console.log('Build complete. Watching for changes...');
  } else {
    console.log('Build complete.');
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});