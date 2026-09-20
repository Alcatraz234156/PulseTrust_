// Apply before styles load to avoid flashing the wrong theme.
(() => {
  const key = 'pulsetrust-theme';
  const root = document.documentElement;
  const normalize = value => value === 'dark' ? 'dark' : 'light';
  let saved;
  try { saved = localStorage.getItem(key); } catch { /* Storage may be disabled. */ }
  root.dataset.theme = normalize(saved);

  function updateToggle() {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    const dark = root.dataset.theme === 'dark';
    button.setAttribute('aria-pressed', String(dark));
    button.title = `Switch to ${dark ? 'light' : 'dark'} mode`;
    document.getElementById('theme-label').textContent = dark ? 'Dark' : 'Light';
  }

  document.addEventListener('DOMContentLoaded', () => {
    updateToggle();
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(key, root.dataset.theme); } catch { /* Keep the in-memory choice. */ }
      updateToggle();
    });
  });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      root.dataset.theme = normalize(event.newValue);
      updateToggle();
    }
  });
})();
