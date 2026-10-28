(() => {
  if (window.lucide) window.lucide.createIcons();

  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('sidebar-toggle');
  if (sidebar && toggle) {
    const collapsed = localStorage.getItem('pccsms-sidebar-collapsed') === 'true';
    sidebar.classList.toggle('is-collapsed', collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
    toggle.title = collapsed ? 'Expand navigation' : 'Collapse navigation';
    toggle.addEventListener('click', () => {
      const next = !sidebar.classList.contains('is-collapsed');
      sidebar.classList.toggle('is-collapsed', next);
      localStorage.setItem('pccsms-sidebar-collapsed', String(next));
      toggle.setAttribute('aria-expanded', String(!next));
      toggle.setAttribute('aria-label', next ? 'Expand navigation' : 'Collapse navigation');
      toggle.title = next ? 'Expand navigation' : 'Collapse navigation';
      if (window.lucide) window.lucide.createIcons();
    });
  }

  const mobileToggle = document.getElementById('mobile-nav-toggle');
  const sidebarScrim = document.getElementById('sidebar-scrim');
  const closeMobileNav = () => {
    sidebar?.classList.remove('is-mobile-open');
    document.body.classList.remove('nav-open');
    mobileToggle?.setAttribute('aria-expanded', 'false');
    mobileToggle?.setAttribute('aria-label', 'Open navigation');
  };
  if (sidebar && mobileToggle) {
    mobileToggle.addEventListener('click', () => {
      const open = !sidebar.classList.contains('is-mobile-open');
      sidebar.classList.toggle('is-mobile-open', open);
      document.body.classList.toggle('nav-open', open);
      mobileToggle.setAttribute('aria-expanded', String(open));
      mobileToggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    });
    sidebarScrim?.addEventListener('click', closeMobileNav);
    sidebar.querySelectorAll('.nav-link').forEach(link => link.addEventListener('click', closeMobileNav));
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMobileNav(); });
  }

  const toast = document.getElementById('toast');
  let timer;
  window.showToast = (message, kind = 'success') => {
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast visible ${kind}`;
    clearTimeout(timer);
    timer = setTimeout(() => toast.classList.remove('visible'), 3000);
  };
  document.querySelectorAll('[data-copy-target]').forEach(button => button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;
    try {
      await navigator.clipboard.writeText(target.innerText.trim());
      window.showToast('Copied.');
    } catch (_) {
      window.showToast('Copy failed. Select the response to copy it.', 'error');
    }
  }));
})();
