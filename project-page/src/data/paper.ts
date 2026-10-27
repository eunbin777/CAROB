import type { Paper } from '../lib/types';

/**
 * CAROB project page. Content follows the EMNLP 2026 Findings camera-ready.
 * Image paths start with "/" and point into /public.
 */
const paper: Paper = {
  title:
    'CAROB: A Benchmark for Cross-Artifact and Authority-aware Reasoning over Organizational Bundles',
  // shortTitle is left out: the title already starts with "CAROB:", so the tab would read "CAROB: CAROB: ...".
  venue: 'Findings of EMNLP 2026',
  year: 2026,
  venuePosition: 'below',

  authors: [
    { name: 'Eunbin Kim', url: 'https://www.linkedin.com/in/eunbin-kim-7206a6250/', affiliationIds: [1] },
    { name: 'Hyuk Namgoong', affiliationIds: [1] },
    { name: 'Wooyoung Go', affiliationIds: [2] },
    { name: 'Seungjin Ryu', affiliationIds: [2] },
    { name: 'Sangkeun Jung', affiliationIds: [1], corresponding: true },
  ],

  affiliations: [
    { id: 1, name: 'Department of Computer Science & Engineering, Chungnam National University, Republic of Korea' },
    { id: 2, name: 'National Security Research Institute, Republic of Korea' },
  ],

  notes: [],

  links: {
    code: 'https://github.com/eunbin777/CAROB',
    dataset: 'https://github.com/eunbin777/CAROB/tree/main/benchmark',
  },

  extraLinks: [],

  teaser: {
    src: '/images/persona.png',
    alt: 'Illustration: Sam, a sales rep outside the launch review group, asks when the launch is; the answer sits in a chat thread, an email and a launch plan marked Confidential: Legal only; the assistant replies with the correct date and sign-off, which is marked correct but leaked.',
    caption:
      '**Correct, but leaked.** Sam is not in the launch review group, and the answer is spread across three artifacts, one of them restricted to Legal. The assistant answers correctly: right for the launch team, a leak for Sam. (Illustrative example.)',
    size: 'text',
    width: 1600,
    height: 948,
    priority: true,
  },
  abstract: `
    Enterprise AI assistants suffer from two failure modes not captured by existing public-web QA benchmarks: *authorized information leakage*, where factually correct answers reach unintended readers, and *aggregation failure*, where evidence scattered across artifacts yields fluent but incomplete responses. Both stem from enterprise authority being per-item and partly body-embedded, a structure that existing benchmarks address along at most one axis. We argue that authority-aware evaluation must be conducted at the per-item level, and instantiate this principle through **C**ross-Artifact and **A**uthority-aware **R**easoning over **O**rganizational **B**undles (CAROB): a synthetic enterprise dataset in which every retrieval-and-citation item carries a time-indexed audience/approval/lifecycle annotation, paired with three tasks that decouple cross-artifact coherence, authority-aware retrieval, and role-conditioned answering. Evaluating five frontier and open-weight LLMs, we find that no single model dominates both axes of the benchmark: each task induces a distinct model ordering, and the model strongest on authority handling ranks last on answer coverage. Two structural patterns hold across the lineup: retrieval-side leakage amplifies substantially at the answer stage, and structural authority filtering eliminates the residual leak band that prompt-level mitigation leaves behind, with both patterns replicating on EnronQA and ACCESS DENIED INC. We release CAROB as an evaluation testbed for authority-aware enterprise system design, together with its per-item annotation, three-task structure, and label-first generation pipeline as reusable infrastructure.
  `,

  sections: [
    {
      id: 'findings',
      title: 'Key Findings',
      content: [
        {
          type: 'figure',
          src: '/images/leaderboard.png',
          alt: 'Scatter plot of five LLMs by authority score and cross-artifact score: Claude Sonnet 4.6 and GPT-5.4 sit top-left, Qwen 3.5 and Llama 4 Maverick in the middle, and Gemini 3.1 Pro bottom-right, leaving the top-right corner empty.',
          caption:
            '**No model dominates both axes.** Horizontal: authority composite *x* = (RetAuthF1 + AuthF1) / 2; vertical: cross-artifact composite *y* = (Coh/100 + AnsF1) / 2.',
          size: 'text',
          width: 1921,
          height: 1560,
        },
        {
          type: 'markdown',
          content: `
            **No model is both careful and complete.** The model strongest on authority handling (Gemini 3.1)
            ranks last on answer coverage, and Sonnet 4.6 is the reverse.
          `,
        },
      ],
    },
  ],

  bibtex: `@inproceedings{kim2026carob,
  title     = {{CAROB}: A Benchmark for Cross-Artifact and Authority-aware Reasoning over Organizational Bundles},
  author    = {Kim, Eunbin and Namgoong, Hyuk and Go, Wooyoung and Ryu, Seungjin and Jung, Sangkeun},
  booktitle = {Findings of the Association for Computational Linguistics: EMNLP 2026},
  year      = {2026}
}`,

  meta: {
    favicon: '/favicon.svg',
  },

  footer:
    'This website is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Feel free to borrow the template.',
};

export default paper;
