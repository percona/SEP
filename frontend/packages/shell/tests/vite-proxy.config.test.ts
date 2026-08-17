/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import { describe, expect, it } from 'vitest';

import viteConfig from '../vite.config';
import viteQaConfig from '../vite.qa.config';

describe('Vite backend proxy prefixes', () => {
  // The SPA fallback would otherwise answer these with index.html: they live
  // outside /api, so each needs its own proxy entry.
  const NON_API_PREFIXES = ['/stream-logs', '/execution-events', '/files'];

  it('proxies the non-/api backend prefixes to the local dev backend', () => {
    const proxy = viteConfig.server?.proxy;
    expect(proxy).toBeDefined();
    for (const prefix of NON_API_PREFIXES) {
      expect(proxy?.[prefix]).toMatchObject({
        target: 'http://localhost:8000',
        changeOrigin: true,
      });
    }
  });

  it('proxies the non-/api backend prefixes to the QA backend', () => {
    const proxy = viteQaConfig.server?.proxy;
    expect(proxy).toBeDefined();
    for (const prefix of NON_API_PREFIXES) {
      expect(proxy?.[prefix]).toMatchObject({
        target: process.env.SEP_QA_BACKEND ?? 'http://127.0.0.1:18002',
        changeOrigin: true,
        cookieDomainRewrite: 'localhost',
      });
    }
  });

  it('drops the retired /static and /legacy proxy entries', () => {
    for (const proxy of [viteConfig.server?.proxy, viteQaConfig.server?.proxy]) {
      expect(proxy?.['/static']).toBeUndefined();
      expect(proxy?.['/legacy']).toBeUndefined();
    }
  });
});
