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

async function fetchServices(serviceType) {
    var params = new URLSearchParams();
    if (serviceType) params.set("service_type", serviceType);
    params.set("limit", "0");
    var url = "/inventory-api/services/?" + params;
    var response = await fetch(url);
    if (!response.ok) return [];
    var data = await response.json();
    return data.items || [];
}

async function populateDestSchemas(destServiceSelect, destDbSelect, opts) {
    var options = opts || {};
    var matched = options.matched || {};
    var unknownLabel = options.unknownLabel || null;
    populateSelect(destDbSelect, [], {
        placeholder: "Select a schema"
    });
    if (destServiceSelect.value && destServiceSelect.value !== "-1") {
        var schemas = await fetchSchemas(destServiceSelect.value);
        if (schemas.length > 0) {
            populateSelect(destDbSelect, schemas, {
                placeholder: "Select a schema"
            });
            destDbSelect.disabled = false;
            var serviceMatch = String(destServiceSelect.value) === String(matched.destServiceId);
            if (serviceMatch && matched.destSchemaId && matched.destSchemaId !== "-1") {
                destDbSelect.value = matched.destSchemaId;
                return;
            }
            if (serviceMatch && matched.destSchemaId === "-1" && unknownLabel) {
                var unknownOpt = document.createElement("option");
                unknownOpt.value = "-1";
                unknownOpt.textContent = unknownLabel;
                unknownOpt.selected = true;
                destDbSelect.appendChild(unknownOpt);
            }
            if (schemas.length === 1) {
                destDbSelect.value = schemas[0].id;
            }
        } else {
            destDbSelect.disabled = true;
        }
    } else {
        destDbSelect.disabled = true;
    }
}

function setManualInputDestHost(enabled, forceToggleChecked, els) {
    if (forceToggleChecked && els.toggle) {
        els.toggle.checked = enabled;
    }
    if (enabled) {
        els.serviceFieldsContainer.style.display = "none";
        els.serviceSelect.value = "";
        els.serviceSelect.disabled = true;
        els.manualInputFields.style.display = "block";
        els.hostInput.disabled = false;
        els.portInput.disabled = false;
        els.dbNameInput.disabled = false;
    } else {
        els.serviceFieldsContainer.style.display = "block";
        els.serviceSelect.disabled = false;
        els.manualInputFields.style.display = "none";
        els.hostInput.disabled = true;
        els.portInput.disabled = true;
        els.dbNameInput.disabled = true;
        els.hostInput.value = "";
        els.portInput.value = "";
        els.dbNameInput.value = "";
    }
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
