#!/usr/bin/env node
/**
 * Post-build check: every local src/href/poster/srcset in dist/*.html
 * must point to a file that actually exists in dist/.
 * Fails the build (exit 1) on broken local assets. External URLs are skipped.
 */
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'dist');
const rawBase = process.env.BASE_PATH && process.env.BASE_PATH !== '/' ? process.env.BASE_PATH : '';
const base = rawBase.replace(/\/$/, '');

const htmlFiles = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (p.endsWith('.html')) htmlFiles.push(p);
  }
})(root);

const attr = /\s(?:src|href|poster|content)="([^"]+)"/g;
const srcset = /\ssrcset="([^"]+)"/g;
const broken = [];
let checked = 0;

for (const file of htmlFiles) {
  const html = readFileSync(file, 'utf8');
  const urls = [];
  for (const m of html.matchAll(attr)) urls.push(m[1]);
  for (const m of html.matchAll(srcset)) m[1].split(',').forEach((s) => urls.push(s.trim().split(/\s+/)[0]));

  for (let url of urls) {
    // Only root-relative paths are local assets we can verify.
    if (!url.startsWith('/') || url.startsWith('//')) continue;
    url = url.split('#')[0].split('?')[0];
    if (base && url.startsWith(base)) url = url.slice(base.length) || '/';
    let target = join(root, decodeURIComponent(url));
    if (url.endsWith('/')) target = join(target, 'index.html');
    checked++;
    if (!existsSync(target)) broken.push(`${file.replace(root, 'dist')}: ${url}`);
  }
}

if (broken.length) {
  console.error(`\n✗ ${broken.length} broken local asset reference(s):`);
  broken.forEach((b) => console.error(`  - ${b}`));
  console.error('\nCheck the paths in src/data/paper.ts and that the files exist under public/.\n');
  process.exit(1);
}
console.log(`✓ Asset check passed: ${checked} local references in ${htmlFiles.length} page(s), none broken.`);
