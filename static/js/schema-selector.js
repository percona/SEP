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
 * Shared utilities for AJAX-powered schema/table cascading dropdowns.
 * Used by: alters, archiver, backups/restore, checksums (create + edit forms).
 */

async function fetchSchemas(serviceId, search) {
    var params = new URLSearchParams();
    if (search) params.set("search", search);
    var url = "/inventory-api/services/" + serviceId + "/schemas?" + params;
    var response = await fetch(url);
    if (!response.ok) return [];
    return response.json();
}

async function fetchTables(schemaId, search) {
    var params = new URLSearchParams();
    if (search) params.set("search", search);
    var url = "/inventory-api/schemas/" + schemaId + "/tables?" + params;
    var response = await fetch(url);
    if (!response.ok) return [];
    return response.json();
}

function populateSelect(selectEl, items, options) {
    var opts = options || {};
    var valueKey = opts.valueKey || "id";
    var textKey = opts.textKey || "name";
    var placeholder = opts.placeholder || "Not selected";
    var emptyPlaceholder = opts.emptyPlaceholder || "None available";
    var preselectValue = opts.preselectValue || null;

    var hasItems = items.length > 0;
    selectEl.disabled = !hasItems;

    while (selectEl.firstChild) {
        selectEl.removeChild(selectEl.firstChild);
    }

    var defaultOpt = document.createElement("option");
    defaultOpt.value = "-1";
    defaultOpt.selected = true;
    defaultOpt.textContent = hasItems ? placeholder : emptyPlaceholder;
    selectEl.appendChild(defaultOpt);

    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var opt = document.createElement("option");
        opt.value = item[valueKey];
        opt.textContent = item[textKey];
        if (preselectValue !== null && String(item[valueKey]) === String(preselectValue)) {
            opt.selected = true;
        }
        selectEl.appendChild(opt);
    }
}
