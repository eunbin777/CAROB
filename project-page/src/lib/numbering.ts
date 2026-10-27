import type { Block, Paper, Section } from './types';

export interface NumberedBlock {
  block: Block;
  /** "Figure 2" / "Table 1" label, or undefined when not numbered. */
  label?: string;
}

export interface NumberedSection extends Omit<Section, 'content'> {
  content: NumberedBlock[];
}

/** Assign Figure / Table numbers in page order (teaser counts as Figure 1). */
export function numberSections(paper: Paper): { teaserLabel?: string; sections: NumberedSection[] } {
  const enabled = paper.numberFigures !== false;
  let fig = 0;
  let tab = 0;

  const label = (b: Block): string | undefined => {
    if (!enabled) return undefined;
    if (b.type === 'figure' || b.type === 'figures' || b.type === 'video') {
      if (b.numbered === false || !b.caption) return undefined;
      return `Figure ${++fig}`;
    }
    if (b.type === 'table') {
      if (b.numbered === false || !b.caption) return undefined;
      return `Table ${++tab}`;
    }
    return undefined;
  };

  let teaserLabel: string | undefined;
  if (paper.teaser) teaserLabel = label({ type: 'figure', ...paper.teaser });

  const sections = paper.sections
    .filter((s) => !s.hidden)
    .map((s) => ({ ...s, content: s.content.map((block) => ({ block, label: label(block) })) }));

  return { teaserLabel, sections };
}
