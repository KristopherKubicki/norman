document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('themeToggle');
  if (!toggle) return;
  const darkPref = localStorage.getItem('darkMode') === 'true';
  setTheme(darkPref);
  toggle.checked = darkPref;
  toggle.addEventListener('change', () => setTheme(toggle.checked));
});

function setTheme(dark) {
  if (dark) {
    document.body.classList.add('dark-mode');
  } else {
    document.body.classList.remove('dark-mode');
  }
  localStorage.setItem('darkMode', dark);
}
