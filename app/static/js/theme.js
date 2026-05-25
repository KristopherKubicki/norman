document.addEventListener('DOMContentLoaded', () => {
  const toggles = Array.from(document.querySelectorAll('.theme-toggle'));
  const selects = Array.from(document.querySelectorAll('.theme-select'));
  const storedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const defaultTheme = document.documentElement.dataset.defaultTheme || 'default';
  const theme = storedTheme || defaultTheme || (prefersDark ? 'dark' : 'default');
  applyTheme(theme);

  selects.forEach(select => {
    select.value = theme;
    select.addEventListener('change', () => {
      applyTheme(select.value);
    });
  });

  toggles.forEach(toggle => {
    toggle.checked = isDarkTheme(theme);
    toggle.addEventListener('change', () => {
      applyTheme(toggle.checked ? 'dark' : defaultTheme || 'default');
    });
  });

  const navbarCollapseEl = document.getElementById('navbarNav');
  if (navbarCollapseEl && window.bootstrap?.Collapse) {
    const collapse = window.bootstrap.Collapse.getOrCreateInstance(navbarCollapseEl, { toggle: false });
    document.querySelectorAll('.navbar .nav-link').forEach((link) => {
      link.addEventListener('click', () => {
        if (window.innerWidth <= 768 && navbarCollapseEl.classList.contains('show')) {
          collapse.hide();
        }
      });
    });
  }
});

function isDarkTheme(theme) {
  return theme === 'dark' || theme === 'graphite' || theme === 'terminal';
}

function applyTheme(theme) {
  const root = document.documentElement;
  const body = document.body;
  root.dataset.theme = theme;
  if (isDarkTheme(theme)) {
    root.classList.add('dark-mode');
    if (body) body.classList.add('dark-mode');
  } else {
    root.classList.remove('dark-mode');
    if (body) body.classList.remove('dark-mode');
  }
  localStorage.setItem('theme', theme);

  const toggles = Array.from(document.querySelectorAll('.theme-toggle'));
  toggles.forEach(toggle => {
    toggle.checked = isDarkTheme(theme);
  });

  const selects = Array.from(document.querySelectorAll('.theme-select'));
  selects.forEach(select => {
    select.value = theme;
  });
}
