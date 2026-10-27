// @ts-check
import { defineConfig } from 'astro/config';

/**
 * GitHub Pages serves project sites from https://<user>.github.io/<repo>/,
 * so the site needs a base path. The deploy workflow fills these in
 * automatically (from actions/configure-pages). Locally they default to "/".
 *
 *   SITE_URL   e.g. https://your-name.github.io   (used for absolute OG image URLs)
 *   BASE_PATH  e.g. /my-paper                     ("" or "/" for user sites / custom domains)
 */
const site = process.env.SITE_URL || undefined;
const base = process.env.BASE_PATH && process.env.BASE_PATH !== '' ? process.env.BASE_PATH : '/';

export default defineConfig({
  site,
  base,
  output: 'static',
  trailingSlash: 'ignore',
  build: {
    // One small stylesheet: inline it to save a request.
    inlineStylesheets: 'always',
  },
  devToolbar: { enabled: false },
});
