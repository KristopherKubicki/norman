(() => {
  const buttons = Array.from(document.querySelectorAll('[data-settings-jump]'));
  const sections = Array.from(document.querySelectorAll('.settings-page .settings-section'));
  if (!buttons.length && !sections.length) return;

  const mobileMedia = window.matchMedia('(max-width: 991px)');
  const CARD_STATE_KEY = 'norman_settings_card_state_v1';

  function isCompactViewport() {
    return Boolean(mobileMedia?.matches);
  }

  function loadCardState() {
    try {
      const raw = localStorage.getItem(CARD_STATE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function saveCardState(state) {
    try {
      localStorage.setItem(CARD_STATE_KEY, JSON.stringify(state));
    } catch (err) {
      // ignore storage errors
    }
  }

  const cardState = loadCardState();
  const cardControls = new Map();

  function setCardOpen(card, open, persist = true) {
    const controls = cardControls.get(card);
    if (!controls) return;
    controls.body.hidden = !open;
    controls.toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    controls.toggle.textContent = open ? 'Hide' : 'Show';
    card.classList.toggle('is-open', open);
    if (!persist) return;
    cardState[controls.key] = open ? 1 : 0;
    saveCardState(cardState);
  }

  sections.forEach((card, index) => {
    const key = card.id || `settings-card-${index}`;
    const title = card.querySelector(':scope > .section-title') || card.querySelector('.section-title');
    if (!title) return;

    const heading = document.createElement('div');
    heading.className = 'settings-card-heading';

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'btn btn-sm btn-outline-secondary settings-card-toggle';

    heading.appendChild(title);
    heading.appendChild(toggle);
    card.insertBefore(heading, card.firstChild);

    const body = document.createElement('div');
    body.className = 'settings-card-body';

    while (heading.nextSibling) {
      body.appendChild(heading.nextSibling);
    }
    card.appendChild(body);

    cardControls.set(card, { key, body, toggle });
    const initial = Object.prototype.hasOwnProperty.call(cardState, key)
      ? Boolean(cardState[key])
      : index === 0;
    setCardOpen(card, initial, false);

    toggle.addEventListener('click', () => {
      const isOpen = card.classList.contains('is-open');
      setCardOpen(card, !isOpen);
    });
  });

  function ensureCardExpanded(sectionId) {
    if (!sectionId) return;
    const section = document.getElementById(sectionId);
    if (!section || !cardControls.has(section)) return;
    setCardOpen(section, true);
  }

  function setActive(targetId) {
    buttons.forEach((btn) => {
      btn.classList.toggle('is-active', btn.getAttribute('data-target') === targetId);
    });
  }

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const target = targetId ? document.getElementById(targetId) : null;
      if (!target) return;
      ensureCardExpanded(targetId);
      setActive(targetId);
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  function syncCardMode() {
    if (!isCompactViewport()) {
      cardControls.forEach((_, card) => setCardOpen(card, true, false));
      return;
    }
    cardControls.forEach((controls, card) => {
      const open = Object.prototype.hasOwnProperty.call(cardState, controls.key)
        ? Boolean(cardState[controls.key])
        : card === sections[0];
      setCardOpen(card, open, false);
    });
  }

  syncCardMode();
  if (typeof mobileMedia.addEventListener === 'function') {
    mobileMedia.addEventListener('change', syncCardMode);
  } else if (typeof mobileMedia.addListener === 'function') {
    mobileMedia.addListener(syncCardMode);
  }

  if (!('IntersectionObserver' in window) || !buttons.length) return;

  const targets = buttons
    .map((btn) => btn.getAttribute('data-target'))
    .filter(Boolean)
    .map((id) => document.getElementById(id))
    .filter(Boolean);

  if (!targets.length) return;

  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible?.target?.id) return;
    setActive(visible.target.id);
  }, {
    root: null,
    threshold: [0.35, 0.6],
    rootMargin: '-20% 0px -45% 0px',
  });

  targets.forEach((target) => observer.observe(target));
})();
