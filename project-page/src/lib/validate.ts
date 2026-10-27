/**
 * Build-time checks for src/data/paper.ts.
 *
 *  - Errors (always fail the build): things that would render a broken page.
 *  - Placeholder warnings: leftovers from the template example
 *    (example.com links, "First Author", placeholder figures, ...).
 *    Printed as warnings normally; they fail the build when PAPER_STRICT=1
 *    (that is what `npm run check` does — run it before publishing a new paper).
 */
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import type { Block, Paper } from './types';

const PLACEHOLDERS: Array<[RegExp, string]> = [
  [/example\.com/i, 'example.com link'],
  [/your-name\/your-repo/i, 'placeholder GitHub URL'],
  [/arxiv\.org\/abs\/0000\.00000/i, 'placeholder arXiv id'],
  [/\b(First|Second|Third|Fourth|Senior) Author\b/, 'placeholder author name'],
  [/\b(University A|Research Lab B|Company C)\b/, 'placeholder affiliation'],
  [/^Conference 2026$/, 'placeholder venue'],
  [/\bCaSeR\b|Calibrated Self-Retrieval/, 'example paper content (CaSeR)'],
  [/author2026caser/, 'example BibTeX'],
];

const PLACEHOLDER_IMAGES = [
  '/images/teaser.svg',
  '/images/method-overview.svg',
  '/images/results-plot.svg',
  '/images/analysis-a.svg',
  '/images/analysis-b.svg',
];

export function validatePaper(paper: Paper) {
  const errors: string[] = [];
  const placeholders = new Set<string>();
  const publicDir = join(process.cwd(), 'public');

  const scan = (value: unknown, where: string) => {
    if (typeof value === 'string') {
      for (const [re, label] of PLACEHOLDERS) if (re.test(value)) placeholders.add(`${label} — ${where}`);
      if (PLACEHOLDER_IMAGES.includes(value)) placeholders.add(`template placeholder figure ${value} — ${where}`);
    } else if (Array.isArray(value)) {
      value.forEach((v, i) => scan(v, `${where}[${i}]`));
    } else if (value && typeof value === 'object') {
      for (const [k, v] of Object.entries(value)) scan(v, where ? `${where}.${k}` : k);
    }
  };
  scan(paper, '');

  const checkImage = (src: string | undefined, alt: string | undefined, where: string) => {
    if (!src) errors.push(`${where}: missing "src"`);
    if (!alt || !alt.trim()) errors.push(`${where}: missing "alt" text (describe the figure for screen readers)`);
    if (src && src.startsWith('/') && !src.startsWith('//') && !existsSync(join(publicDir, src))) {
      errors.push(`${where}: file not found: public${src}`);
    }
    if (src && /\.pdf$/i.test(src)) {
      errors.push(`${where}: "${src}" is a PDF — browsers can't show PDFs in <img>. Convert it to PNG/SVG (see README).`);
    }
  };

  if (!paper.title?.trim()) errors.push('title is empty');
  if (!paper.authors?.length) errors.push('authors is empty');
  if (!paper.abstract?.trim()) errors.push('abstract is empty');

  const affIds = new Set((paper.affiliations ?? []).map((a) => String(a.id)));
  paper.authors?.forEach((a, i) => {
    if (!a.name?.trim()) errors.push(`authors[${i}]: missing name`);
    a.affiliationIds?.forEach((id) => {
      if (!affIds.has(String(id))) errors.push(`authors[${i}] (${a.name}): affiliation id ${id} is not in "affiliations"`);
    });
  });

  if (paper.teaser) checkImage(paper.teaser.src, paper.teaser.alt, 'teaser');

  const ids = new Set<string>(['abstract', 'bibtex']);
  paper.sections?.forEach((s, si) => {
    const at = `sections[${si}] "${s.title}"`;
    if (!s.id || !/^[A-Za-z][\w-]*$/.test(s.id)) errors.push(`${at}: id must be letters/digits/-/_ (got "${s.id}")`);
    if (ids.has(s.id)) errors.push(`${at}: duplicate section id "${s.id}"`);
    ids.add(s.id);

    s.content?.forEach((b: Block, bi) => {
      const where = `${at} → content[${bi}] (${b.type})`;
      if (b.type === 'figure') checkImage(b.src, b.alt, where);
      if (b.type === 'figures') b.items.forEach((it, ii) => checkImage(it.src, it.alt, `${where} item ${ii}`));
      if (b.type === 'video' && b.src.startsWith('/') && !existsSync(join(publicDir, b.src)))
        errors.push(`${where}: file not found: public${b.src}`);
      if (b.type === 'table') {
        const n = b.columns.length;
        b.rows.forEach((r, ri) => {
          const cells = Array.isArray(r) ? r : 'cells' in r ? r.cells : null;
          if (cells && cells.length !== n)
            errors.push(`${where}: row ${ri} has ${cells.length} cells but there are ${n} columns`);
        });
        if (b.headerGroups) {
          const span = b.headerGroups.reduce((s, g) => s + g.span, 0);
          if (span !== n) errors.push(`${where}: headerGroups spans add up to ${span}, but there are ${n} columns`);
        }
      }
    });
  });

  const strict = process.env.PAPER_STRICT === '1' || process.env.PAPER_STRICT === 'true';

  if (placeholders.size) {
    const list = [...placeholders].map((p) => `  - ${p}`).join('\n');
    const msg = `[paper.ts] Template placeholder content is still present:\n${list}`;
    if (strict) errors.push(msg);
    else console.warn(`\n⚠ ${msg}\n  (Run "npm run check" to treat these as errors.)\n`);
  }

  if (errors.length) {
    throw new Error(`\n\n✗ src/data/paper.ts has ${errors.length} problem(s):\n${errors.map((e) => `  - ${e}`).join('\n')}\n`);
  }
}
