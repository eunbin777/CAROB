/**
 * Scroll reveal — "content rises gently from slightly below".
 *
 * Progressive enhancement:
 *  - An inline script in <head> adds `reveal-on` to <html> only when JS runs,
 *    IntersectionObserver exists and the user has NOT asked for reduced motion.
 *  - CSS hides [data-reveal] elements only under `html.reveal-on`, so without JS
 *    (or with reduced motion) everything is visible immediately.
 *  - If this script never runs, a 2.5s failsafe in <head> removes `reveal-on`.
 *
 * Elements:
 *  - [data-reveal="hero"]  → revealed on page load, in DOM order, 80ms apart.
 *  - [data-reveal]         → revealed once when they first enter the viewport.
 *                            Elements entering together are staggered 70ms apart
 *                            (heading → text → figure/table).
 */

const HERO_STAGGER_MS = 80;
const BODY_STAGGER_MS = 70;
const MAX_STAGGER_STEPS = 4;
const THRESHOLD = 0.12;

declare global {
  interface Window {
    __revealReady?: boolean;
  }
}

function show(el: HTMLElement, delayMs: number) {
  el.style.setProperty('--reveal-delay', `${delayMs}ms`);
  el.classList.add('is-visible');
  // Clear the delay afterwards so it never affects anything else.
  el.addEventListener(
    'transitionend',
    () => {
      el.style.removeProperty('--reveal-delay');
    },
    { once: true }
  );
}

function byDocumentOrder(a: Element, b: Element) {
  return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

export function initReveal() {
  window.__revealReady = true;
  const root = document.documentElement;
  if (!root.classList.contains('reveal-on')) return;

  // 1) Hero entrance on load.
  const hero = Array.from(document.querySelectorAll<HTMLElement>('[data-reveal="hero"]'));
  // Two frames so the hidden state is painted first and the transition actually runs.
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      hero.forEach((el, i) => show(el, i * HERO_STAGGER_MS));
    })
  );

  // 2) Body: once, on first entry into the viewport.
  const items = Array.from(document.querySelectorAll<HTMLElement>('[data-reveal]:not([data-reveal="hero"])'));

  const observer = new IntersectionObserver(
    (entries) => {
      const entering = entries
        .filter((e) => {
          if (!e.isIntersecting) return false;
          // Very tall elements may never reach the ratio threshold; accept them
          // once they cover a quarter of the viewport.
          const vh = e.rootBounds?.height ?? window.innerHeight;
          return e.intersectionRatio >= THRESHOLD || e.intersectionRect.height >= vh * 0.25;
        })
        .map((e) => e.target as HTMLElement)
        .sort(byDocumentOrder);

      entering.forEach((el, i) => {
        observer.unobserve(el);
        show(el, Math.min(i, MAX_STAGGER_STEPS) * BODY_STAGGER_MS);
      });
    },
    { threshold: [0, THRESHOLD, 0.25], rootMargin: '0px 0px -6% 0px' }
  );

  items.forEach((el) => observer.observe(el));
}
