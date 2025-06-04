import React from 'react';
import { useInfiniteQuery } from 'react-query';

export default function InfiniteMessages({ botId }) {
  const fetchMessages = async ({ pageParam = null }) => {
    const params = new URLSearchParams();
    if (pageParam) params.set('cursor', pageParam);
    params.set('limit', 20);
    const resp = await fetch(`/api/bots/${botId}/messages?` + params.toString());
    if (!resp.ok) throw new Error('Error fetching messages');
    return resp.json();
  };

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    status,
  } = useInfiniteQuery(['messages', botId], fetchMessages, {
    getNextPageParam: (lastPage) => {
      if (lastPage.length === 0) return undefined;
      return lastPage[lastPage.length - 1].created_at;
    },
  });

  const observer = React.useRef();
  const lastMessageRef = React.useCallback(
    (node) => {
      if (isFetchingNextPage) return;
      if (observer.current) observer.current.disconnect();
      observer.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && hasNextPage) {
          fetchNextPage();
        }
      });
      if (node) observer.current.observe(node);
    },
    [isFetchingNextPage, fetchNextPage, hasNextPage]
  );

  if (status === 'loading') return <p>Loading...</p>;
  if (status === 'error') return <p>Error loading messages</p>;

  return (
    <div role="region">
      {data.pages.map((page, pageIndex) => (
        <React.Fragment key={pageIndex}>
          {page.map((msg, i) => {
            if (pageIndex === data.pages.length - 1 && i === page.length - 1) {
              return (
                <div ref={lastMessageRef} key={msg.id} className="message">
                  {msg.text}
                </div>
              );
            }
            return (
              <div key={msg.id} className="message">
                {msg.text}
              </div>
            );
          })}
        </React.Fragment>
      ))}
      {isFetchingNextPage && <p>Loading more...</p>}
    </div>
  );
}
