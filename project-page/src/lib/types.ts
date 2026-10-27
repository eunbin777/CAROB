/**
 * Data schema for one paper page.
 * You normally never edit this file — edit `src/data/paper.ts` instead.
 */

export type IconName =
  | 'paper'
  | 'arxiv'
  | 'code'
  | 'demo'
  | 'dataset'
  | 'model'
  | 'video'
  | 'slides'
  | 'poster'
  | 'link';

export interface Author {
  name: string;
  /** Personal homepage. Omit to render plain text. */
  url?: string;
  /** Ids from `affiliations`. Rendered as superscripts. */
  affiliationIds?: Array<number | string>;
  /** Adds "*" and an "Equal contribution" note. */
  equalContribution?: boolean;
  /** Adds "†" and a "Corresponding author" note. */
  corresponding?: boolean;
}

export interface Affiliation {
  id: number | string;
  name: string;
}

/** Standard resource buttons. Missing / empty values are hidden automatically. */
export interface PaperLinks {
  paper?: string;
  arxiv?: string;
  code?: string;
  demo?: string;
  dataset?: string;
  model?: string;
}

/** Any additional button (Slides, Video, Poster, ...). Same style as the standard ones. */
export interface ExtraLink {
  label: string;
  url: string;
  icon?: IconName;
}

/* ---------------------------------------------------------------- blocks */

/** Markdown text (GFM: lists, tables, links, code, inline HTML). */
export interface MarkdownBlock {
  type: 'markdown';
  content: string;
}

/**
 * Layout width of a figure / table:
 *  - 'text' : same width as the paragraphs (~760px)
 *  - 'wide' : full content width (~1000px), slightly wider than text (default)
 */
export type BlockSize = 'text' | 'wide';

export interface FigureBlock {
  type: 'figure';
  /** Path under /public, e.g. "/images/method.png", or an absolute URL. */
  src: string;
  alt: string;
  /** Markdown allowed (inline). */
  caption?: string;
  size?: BlockSize;
  /** Intrinsic pixel size. Optional but recommended (prevents layout shift). */
  width?: number;
  height?: number;
  /** Cap the rendered width, e.g. "640px" for a small diagram. */
  maxWidth?: string;
  /** Set false to skip "Figure N." numbering for this figure. */
  numbered?: boolean;
  /** Load immediately (use for the teaser / first image only). */
  priority?: boolean;
}

/** Two to four images side by side, with optional sub-captions and one shared caption. */
export interface FigureRowBlock {
  type: 'figures';
  items: Array<{ src: string; alt: string; caption?: string; width?: number; height?: number }>;
  caption?: string;
  size?: BlockSize;
  numbered?: boolean;
}

export interface VideoBlock {
  type: 'video';
  src: string;
  poster?: string;
  caption?: string;
  /** Autoplay muted & looped (like a GIF). Otherwise shows controls. */
  autoplay?: boolean;
  size?: BlockSize;
  numbered?: boolean;
}

export type TableCell = string | number;

export interface TableRowObject {
  cells: TableCell[];
  /** Highlight this row (e.g. "Ours"). */
  highlight?: boolean;
}

/** A full-width label row that groups the rows below it, e.g. "Retrieval-based methods". */
export interface TableGroupRow {
  group: string;
}

export type TableRow = TableCell[] | TableRowObject | TableGroupRow;

export interface TableBlock {
  type: 'table';
  /** Markdown allowed (inline). Shown above the table, as is conventional for tables. */
  caption?: string;
  /** Optional spanning header row above `columns`, e.g. dataset names. */
  headerGroups?: Array<{ label: string; span: number }>;
  columns: string[];
  /** Cells accept inline markdown: **best**, <u>second</u>, `code`, etc. */
  rows: TableRow[];
  /** Per-column alignment. Default: first column left, others center. */
  align?: Array<'left' | 'center' | 'right'>;
  /** Small note under the table (markdown inline). */
  note?: string;
  size?: BlockSize;
  numbered?: boolean;
}

/** Raw HTML escape hatch for anything the other blocks don't cover. */
export interface HtmlBlock {
  type: 'html';
  content: string;
}

export type Block =
  | MarkdownBlock
  | FigureBlock
  | FigureRowBlock
  | VideoBlock
  | TableBlock
  | HtmlBlock;

export interface Section {
  /** Used as the anchor: https://.../#method */
  id: string;
  /** H2 heading text. */
  title: string;
  content: Block[];
  /** Temporarily hide a section without deleting it. */
  hidden?: boolean;
}

export interface Paper {
  title: string;
  /** Short name / acronym, used in the browser tab. */
  shortTitle?: string;
  /** e.g. "ACL 2026" or "NeurIPS 2026 (Spotlight)". */
  venue?: string;
  year?: number;
  /** Where the venue line sits in the hero. Default: 'below' the title. */
  venuePosition?: 'above' | 'below';

  authors: Author[];
  affiliations: Affiliation[];
  /** Extra small notes under the affiliations (e.g. "Work done during an internship at ..."). */
  notes?: string[];

  links: PaperLinks;
  extraLinks?: ExtraLink[];

  /** Optional figure shown right after the hero, before the abstract. */
  teaser?: Omit<FigureBlock, 'type'>;

  /** Markdown. Rendered as the first section ("Abstract"). */
  abstract: string;
  /** Rename the abstract heading if needed. */
  abstractTitle?: string;

  /** Body sections, in order. Add, remove, rename freely. */
  sections: Section[];

  /** Raw BibTeX. Omit or leave empty to hide the BibTeX section. */
  bibtex?: string;

  /** Prefix captions with "Figure N." / "Table N.". Default: true. */
  numberFigures?: boolean;

  /** <html lang>. Default: 'en'. */
  lang?: string;

  meta?: {
    /** <meta name="description">. Default: first ~160 chars of the abstract. */
    description?: string;
    /** Social preview image (path under /public). Recommended 1200×630. */
    ogImage?: string;
    /** Path under /public. Default: /favicon.svg */
    favicon?: string;
  };

  /** Footer line (inline markdown). */
  footer?: string;
}
