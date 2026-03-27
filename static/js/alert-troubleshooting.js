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

/* Animate <details> accordion sections via grid-template-rows transitions. */

document.addEventListener("DOMContentLoaded", function() {
    document.querySelectorAll(".at-section").forEach(function(details) {
        var summary = details.querySelector(".at-section-header");
        var body = details.querySelector(".at-section-body");
        if (!summary || !body) return;

        summary.addEventListener("click", function(e) {
            e.preventDefault();

            if (details.open) {
                // Collapse: animate grid rows to 0fr, then remove open
                body.style.gridTemplateRows = "0fr";
                body.addEventListener(
                    "transitionend",
                    function() {
                        details.open = false;
                        body.style.gridTemplateRows = "";
                    }, {
                        once: true
                    }
                );
            } else {
                // Expand: set open, force 0fr, then animate to 1fr
                details.open = true;
                body.style.gridTemplateRows = "0fr";
                requestAnimationFrame(function() {
                    requestAnimationFrame(function() {
                        body.style.gridTemplateRows = "1fr";
                        body.addEventListener(
                            "transitionend",
                            function() {
                                body.style.gridTemplateRows = "";
                            }, {
                                once: true
                            }
                        );
                    });
                });
            }
        });
    });
});
