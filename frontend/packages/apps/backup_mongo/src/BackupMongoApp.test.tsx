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

import { Children, type ReactElement } from 'react';
import { describe, expect, it } from 'vitest';
import { BackupMongoApp } from './BackupMongoApp';
import { restoreMongoCreateForm, restoreMongoEditForm } from './restoreMongoCreateForm';

type AnyProps = Record<string, unknown>;

// BackupMongoApp holds no hooks of its own, so calling it yields the element
// tree without mounting. Walk the <Routes> to read each tab's SchemaDrivenApp
// props — this fails if the restores tab loses its custom edit-form wiring,
// which prop-only slot tests cannot catch.
function schemaAppPropsByRoutePath(): Record<string, AnyProps> {
  const tree = BackupMongoApp() as ReactElement<{ children: ReactElement[] }>;
  const children = Children.toArray(tree.props.children) as ReactElement<AnyProps>[];
  const routesEl = children.find(
    (child) =>
      Array.isArray(child.props.children) &&
      (child.props.children as ReactElement<AnyProps>[]).some(
        (route) => route?.props?.path !== undefined,
      ),
  ) as ReactElement<{ children: ReactElement<AnyProps>[] }>;

  const byPath: Record<string, AnyProps> = {};
  for (const route of Children.toArray(routesEl.props.children) as ReactElement<AnyProps>[]) {
    const path = route.props.path as string | undefined;
    const element = route.props.element as ReactElement<AnyProps> | undefined;
    if (path && element) {
      byPath[path] = element.props;
    }
  }
  return byPath;
}

describe('BackupMongoApp route wiring', () => {
  it('wires the custom create and edit form slots on the restores tab', () => {
    const restores = schemaAppPropsByRoutePath()['restores/*'];

    expect(restores.renderCreateForm).toBe(restoreMongoCreateForm);
    expect(restores.renderEditForm).toBe(restoreMongoEditForm);
  });

  it('leaves the backups tab on the framework default edit renderer', () => {
    const backups = schemaAppPropsByRoutePath()['backups/*'];

    expect(backups.renderEditForm).toBeUndefined();
    expect(backups.renderCreateForm).toBeUndefined();
  });
});
