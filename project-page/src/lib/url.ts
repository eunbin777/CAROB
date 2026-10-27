/**
 * Prefix root-relative paths ("/images/x.png") with the site base path,
 * so the same data works at "/" locally and at "/<repo>/" on GitHub Pages.
 * Absolute URLs, protocol-relative URLs, anchors and relative paths are left alone.
 */
const RAW_BASE = import.meta.env.BASE_URL || '/';
const BASE = RAW_BASE.endsWith('/') ? RAW_BASE.slice(0, -1) : RAW_BASE;

export function withBase(path: string): string;
export function withBase(path: string | undefined): string | undefined;
export function withBase(path: string | undefined): string | undefined {
  if (!path) return path;
  if (/^([a-z][a-z0-9+.-]*:|\/\/|#|\?)/i.test(path)) return path;
  if (!path.startsWith('/')) return path;
  return `${BASE}${path}`;
}

export function isExternal(url: string): boolean {
  return /^(https?:)?\/\//i.test(url);
}
