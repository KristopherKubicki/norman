import { loadView } from '../core/index';

document.addEventListener('DOMContentLoaded', () => {
  const view = document.body.dataset.view;
  if (view) {
    loadView(view);
  }
});
