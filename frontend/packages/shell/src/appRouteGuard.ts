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

/**
 * Shared app-route guard wrapper.
 *
 * Extracted from ``appRegistry`` so both the router builder and
 * ``SchemaDrivenAppResolver`` can wrap a resolved app route without importing
 * each other (``appRegistry`` builds the routes, the resolver renders one at a
 * time).
 */

import { createElement, type ReactElement } from 'react';
import AppDisabledGuard from './components/AppDisabledGuard';

/** Protected apps are never gated — toggle returns 409 on the backend. */
const UNGUARDED_APP_KEYS = new Set(['inventory']);

/** Wrap an app route element in ``AppDisabledGuard`` unless the app is unguarded. */
export function wrapAppRoute(appKey: string, element: ReactElement): ReactElement {
  if (UNGUARDED_APP_KEYS.has(appKey)) {
    return element;
  }
  // `children` rides in the props object rather than `createElement`'s third
  // argument: this module is plain `.ts` so JSX (what the rule wants) is not
  // available, and `AppDisabledGuardProps.children` is required, which the
  // third-argument overload does not satisfy for the type checker.
  // eslint-disable-next-line react/no-children-prop
  return createElement(AppDisabledGuard, { appKey, children: element });
}
