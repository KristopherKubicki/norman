(function(){
  function applyTheme(theme){
    var root=document.documentElement;
    Object.entries(theme.colors).forEach(function(entry){
      root.style.setProperty('--color-'+entry[0], entry[1]);
    });
    Object.entries(theme.spacing).forEach(function(entry){
      root.style.setProperty('--spacing-'+entry[0], entry[1]);
    });
    Object.entries(theme.typography).forEach(function(entry){
      root.style.setProperty('--typography-'+entry[0], entry[1]);
    });
  }

  var lightTheme={
    colors:{
      background:'#f8f9fa',
      text:'#212529',
      link:'#333',
      border:'#dee2e6',
      systemMessage:'#f1f1f1',
      assistantMessage:'#f0f0f0',
      userMessage:'#ffffff'
    },
    spacing:{xs:'0.25rem',sm:'0.5rem',md:'1rem',lg:'1.5rem',xl:'2rem'},
    typography:{fontFamily:"'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",baseFontSize:'16px'}
  };

  var darkTheme={
    colors:{
      background:'#121212',
      text:'#f8f9fa',
      link:'#f8f9fa',
      border:'#1e1e1e',
      systemMessage:'#1e1e1e',
      assistantMessage:'#1e1e1e',
      userMessage:'#1e1e1e'
    },
    spacing:lightTheme.spacing,
    typography:lightTheme.typography
  };

  function setTheme(dark){
    applyTheme(dark?darkTheme:lightTheme);
    if(dark){
      document.documentElement.classList.add('dark-mode');
    } else {
      document.documentElement.classList.remove('dark-mode');
    }
    localStorage.setItem('theme', dark ? 'dark' : 'light');
  }

  document.addEventListener('DOMContentLoaded', function(){
    var toggle=document.getElementById('themeToggle');
    if(!toggle) return;
    var storedTheme=localStorage.getItem('theme');
    var prefersDark=window.matchMedia('(prefers-color-scheme: dark)').matches;
    var darkPref=storedTheme ? storedTheme==='dark' : prefersDark;
    setTheme(darkPref);
    toggle.checked=darkPref;
    toggle.addEventListener('change', function(){ setTheme(toggle.checked); });
  });

  window.applyTheme=applyTheme;
  window.setTheme=setTheme;
})();
