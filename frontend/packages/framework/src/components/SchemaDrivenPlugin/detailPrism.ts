import Prism from 'prismjs';
import type { PrismLib } from 'prism-react-renderer';
import 'prismjs/components/prism-sql.js';
import 'prismjs/components/prism-json.js';

/** Prism instance with SQL + JSON grammars for ``Highlight`` (``prism-react-renderer``). */
export const detailPrism: PrismLib = Prism as unknown as PrismLib;
