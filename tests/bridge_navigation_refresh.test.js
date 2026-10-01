const fs = require('fs');
const source = fs.readFileSync('app/static/js/bridge.js', 'utf8');
const code = source.slice(source.indexOf('  const navigationMarkup ='), source.indexOf('  function renderGroups('));
let update, list;
beforeEach(() => {
  document.body.innerHTML = '<input><div id="list"></div>';
  list = document.querySelector('#list');
  update = new Function(code + ';return updateNavigationMarkup;')();
});
test('repeated background refresh preserves buttons and keyboard focus', () => {
  const html = '<button data-agent="norman"><svg><use href="#icon"/></svg>Norman</button>';
  update(list, html);
  const button = list.firstChild;
  button.focus();
  for (let i = 0; i < 20; i++) update(list, html);
  expect(list.firstChild).toBe(button);
  expect(document.activeElement).toBe(button);
});
test('changed status and reordered rooms retain focus on the same room without scrolling', () => {
  update(list, '<button data-conversation-id="a">A</button><button data-conversation-id="b">B</button>');
  list.lastChild.focus();
  list.scrollTop = 120;
  const focus = jest.spyOn(HTMLElement.prototype, 'focus');
  update(list, '<button data-conversation-id="b">B · Working</button><button data-conversation-id="a">A</button>');
  expect(document.activeElement.textContent).toBe('B · Working');
  expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
  expect(list.scrollTop).toBe(120);
  focus.mockRestore();
});
test('refresh never steals focus from the composer or focuses a different removed item', () => {
  update(list, '<button data-agent="norman">Norman</button>');
  const input = document.querySelector('input');
  input.focus();
  update(list, '<button data-agent="norman">Updated</button>');
  expect(document.activeElement).toBe(input);
  list.firstChild.focus();
  update(list, '<button data-agent="other">Other</button>');
  expect(document.activeElement).not.toBe(list.firstChild);
});
test('login expiry removes previous workspace controls and repeated empty states stay stable', () => {
  update(list, '<button data-agent="norman">Norman</button>');
  update(list, '<div>Log in</div>');
  const empty = list.firstChild;
  update(list, '<div>Log in</div>');
  expect(list.querySelector('button')).toBeNull();
  expect(list.firstChild).toBe(empty);
});
