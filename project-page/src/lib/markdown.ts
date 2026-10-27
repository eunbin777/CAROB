import { Marked } from 'marked';
import { withBase, isExternal } from './url';

const escapeAttr = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const marked = new Marked({ gfm: true });

marked.use({
  renderer: {
    link({ href, title, tokens }) {
      const text = this.parser.parseInline(tokens);
      const ext = isExternal(href);
      return `<a href="${escapeAttr(withBase(href))}"${title ? ` title="${escapeAttr(title)}"` : ''}${
        ext ? ' target="_blank" rel="noopener noreferrer"' : ''
      }>${text}</a>`;
    },
    image({ href, title, text }) {
      return `<img src="${escapeAttr(withBase(href))}" alt="${escapeAttr(text)}"${
        title ? ` title="${escapeAttr(title)}"` : ''
      } loading="lazy" decoding="async">`;
    },
    // Wide markdown tables scroll horizontally instead of breaking the layout.
    table(token) {
      const html = marked.Renderer.prototype.table.call(this, token);
      return `<div class="table-scroll" tabindex="0" role="region" aria-label="Table">${html}</div>`;
    },
  },
});

/**
 * Remove the common indentation of a template literal, so content can be
 * indented naturally inside paper.ts without turning into code blocks.
 */
export function dedent(input: string): string {
  const lines = input.replace(/\t/g, '  ').split('\n');
  while (lines.length && lines[0].trim() === '') lines.shift();
  while (lines.length && lines[lines.length - 1].trim() === '') lines.pop();
  const indents = lines.filter((l) => l.trim()).map((l) => l.match(/^ */)![0].length);
  const min = indents.length ? Math.min(...indents) : 0;
  return lines.map((l) => l.slice(min)).join('\n');
}

/** Block-level markdown → HTML. */
export function renderMarkdown(src: string): string {
  return marked.parse(dedent(src), { async: false }) as string;
}

/** Inline markdown (captions, table cells) → HTML, without a wrapping <p>. */
export function renderInline(src: string | number): string {
  return marked.parseInline(String(src), { async: false }) as string;
}

/** Plain text (for meta descriptions / aria labels). */
export function toPlainText(src: string): string {
  return renderMarkdown(src)
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim();
}
