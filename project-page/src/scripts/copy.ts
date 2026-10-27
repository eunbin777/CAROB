/** Copy-to-clipboard for elements with [data-copy-target="<id>"]. */

const FEEDBACK_MS = 1800;

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  // Fallback for http:// previews and older browsers.
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  ta.remove();
  return ok;
}

export function initCopyButtons() {
  document.querySelectorAll<HTMLButtonElement>('[data-copy-target]').forEach((btn) => {
    if (btn.dataset.copyBound) return;
    btn.dataset.copyBound = 'true';
    let timer: number | undefined;

    btn.addEventListener('click', async () => {
      const target = document.getElementById(btn.dataset.copyTarget!);
      if (!target) return;
      const ok = await copyText(target.textContent ?? '');
      const status = btn.getAttribute('aria-describedby');
      const statusEl = status ? document.getElementById(status) : null;

      btn.classList.toggle('is-copied', ok);
      if (statusEl) statusEl.textContent = ok ? 'BibTeX copied to clipboard' : 'Copy failed — please select the text manually';

      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        btn.classList.remove('is-copied');
        if (statusEl) statusEl.textContent = '';
      }, FEEDBACK_MS);
    });
  });
}
