import React from 'react';
import { render, screen } from '@testing-library/react';
import InfiniteMessages from '../InfiniteMessages.jsx';

// Mock react-query's useInfiniteQuery to control component state
jest.mock('react-query', () => ({
  useInfiniteQuery: jest.fn(() => ({
    data: { pages: [[]] },
    fetchNextPage: jest.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
    status: 'success'
  }))
}));

describe('InfiniteMessages', () => {
  it('renders messages container', () => {
    render(<InfiniteMessages botId="1" />);
    const container = screen.getByRole('region');
    expect(container).toBeInTheDocument();
  });
});
