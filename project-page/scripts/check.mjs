#!/usr/bin/env node
/**
 * `npm run check` — strict build for publishing a new paper.
 * Same as `npm run build`, but leftover template placeholders
 * (example.com links, "First Author", placeholder figures, ...) fail the build.
 * Works on macOS, Linux and Windows.
 */
import { spawnSync } from 'node:child_process';

const r = spawnSync('npm', ['run', 'build'], {
  stdio: 'inherit',
  shell: true,
  env: { ...process.env, PAPER_STRICT: '1' },
});
if (r.status === 0) console.log('\n✓ Ready to publish: no errors, no template placeholders left.\n');
process.exit(r.status ?? 1);
