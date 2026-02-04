document.addEventListener('DOMContentLoaded', () => {
  const toggles = Array.from(document.querySelectorAll('.theme-toggle'));
  const storedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const isDark = storedTheme ? storedTheme === 'dark' : prefersDark;
  setTheme(isDark);
  toggles.forEach(toggle => {
    toggle.checked = isDark;
    toggle.addEventListener('change', () => setTheme(toggle.checked));
  });
});

function setTheme(dark) {
  if (dark) {
    document.documentElement.classList.add('dark-mode');
  } else {
    document.documentElement.classList.remove('dark-mode');
  }
  localStorage.setItem('theme', dark ? 'dark' : 'light');
}
