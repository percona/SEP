import { useMemo, useState } from 'react';

export interface LogSearchState {
  query: string;
  setQuery: (q: string) => void;
  filteredText: string;
  matchCount: number;
}

export function useLogSearch(text: string): LogSearchState {
  const [query, setQuery] = useState('');

  const { filteredText, matchCount } = useMemo(() => {
    if (!query) {
      return { filteredText: text, matchCount: 0 };
    }
    const needle = query.toLowerCase();
    const lines = text.split('\n');
    const matches = lines.filter((line) => line.toLowerCase().includes(needle));
    return { filteredText: matches.join('\n'), matchCount: matches.length };
  }, [text, query]);

  return { query, setQuery, filteredText, matchCount };
}
