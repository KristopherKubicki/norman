import React from 'react';
import ReactDOM from 'react-dom/client';
import InfiniteMessages from './InfiniteMessages.jsx';

const mount = document.getElementById('messages-log');
if (mount) {
  const botId = mount.dataset.botId || '1';
  ReactDOM.createRoot(mount).render(<InfiniteMessages botId={botId} />);
}
