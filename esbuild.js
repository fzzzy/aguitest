#!/usr/bin/env node

import esbuild from 'esbuild';
import chokidar from 'chokidar';
import { exec } from 'child_process';

(async function main() {
  const isServe = process.argv.includes('--serve');

  const buildConfig = {
    entryPoints: ['./src/index.ts'],
    bundle: true,
    sourcemap: true,
    outdir: 'dist',
    format: 'esm',
    target: 'es2022',
    logLevel: 'info',
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

    let watcher = chokidar.watch(['src'], {
      ignored: /(^|[\/\\])\../,
      persistent: true,
    });

    watcher
      .on('change', async (path) => {
        console.log(`File ${path} has been changed`);
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