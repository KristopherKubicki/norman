export interface ThemeTokens {
  colors: Record<string, string>;
  spacing: Record<string, string>;
  typography: Record<string, string>;
}

export const lightTheme: ThemeTokens = {
  colors: {
    background: '#f8f9fa',
    text: '#212529',
    link: '#333',
    border: '#dee2e6',
    systemMessage: '#f1f1f1',
    assistantMessage: '#f0f0f0',
    userMessage: '#ffffff'
  },
  spacing: {
    xs: '0.25rem',
    sm: '0.5rem',
    md: '1rem',
    lg: '1.5rem',
    xl: '2rem'
  },
  typography: {
    fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",
    baseFontSize: '16px'
  }
};

export const darkTheme: ThemeTokens = {
  colors: {
    background: '#121212',
    text: '#f8f9fa',
    link: '#f8f9fa',
    border: '#1e1e1e',
    systemMessage: '#1e1e1e',
    assistantMessage: '#1e1e1e',
    userMessage: '#1e1e1e'
  },
  spacing: lightTheme.spacing,
  typography: lightTheme.typography
};

export function applyTheme(theme: ThemeTokens): void {
  const root = document.documentElement;
  Object.entries(theme.colors).forEach(([key, value]) => {
    root.style.setProperty(`--color-${key}`, value);
  });
  Object.entries(theme.spacing).forEach(([key, value]) => {
    root.style.setProperty(`--spacing-${key}`, value);
  });
  Object.entries(theme.typography).forEach(([key, value]) => {
    root.style.setProperty(`--typography-${key}`, value);
  });
}

export function setTheme(dark: boolean): void {
  applyTheme(dark ? darkTheme : lightTheme);
  if (dark) {
    document.body.classList.add('dark-mode');
  } else {
    document.body.classList.remove('dark-mode');
  }
  localStorage.setItem('darkMode', String(dark));
}

document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('themeToggle') as HTMLInputElement | null;
  if (!toggle) return;
  const darkPref = localStorage.getItem('darkMode') === 'true';
  setTheme(darkPref);
  toggle.checked = darkPref;
  toggle.addEventListener('change', () => setTheme(toggle.checked));
});
