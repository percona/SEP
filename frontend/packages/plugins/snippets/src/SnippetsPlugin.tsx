import { Route, Routes } from 'react-router-dom';
import { SnippetDetailPage } from './SnippetDetailPage';
import { SnippetsListPage } from './SnippetsListPage';

/**
 * Snippets plugin entry point — composes its own routes because the legacy
 * snippets UI is snippet-centric (list of files → detail page combining
 * preview + execution form + history) rather than the framework's
 * task-centric default.
 */
export function SnippetsPlugin() {
  return (
    <Routes>
      <Route index element={<SnippetsListPage />} />
      <Route path=":filename" element={<SnippetDetailPage />} />
    </Routes>
  );
}
