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

$(document).ready(function() {
    window.ChainBuilder = function($container, options) {
        this.$container = $container;
        this.formId = options.formId || $container.data('form-id');
        this.taskName = options.taskName || $container.data('task-name');
        this.inputName = options.inputName || $container.data('input-name') || 'chain_task_names';
        this.chain = [];
        this.chainOnFailure = $container.data('chain-on-failure') === true || $container.data('chain-on-failure') === 'true';

        this.$sequence = $container.find('.chain-sequence');
        this.$select = $container.find('.chain-task-select');
        this.$chainOptions = $container.find('.chain-options');
        this.$chainOnFailureCheckbox = $container.find('.chain-on-failure-checkbox');

        var initialChain = options.initialChain || $container.data('initial-chain');
        if (initialChain) {
            if (typeof initialChain === 'string') {
                try {
                    initialChain = JSON.parse(initialChain);
                } catch (e) {
                    initialChain = [];
                }
            }
            for (var i = 0; i < initialChain.length; i++) {
                this.chain.push(initialChain[i]);
            }
        }

        this._bindEvents();
        this._render();
    };

    ChainBuilder.prototype._wouldCreateCycle = function(name) {
        if (name === this.taskName) {
            return true;
        }
        for (var i = 0; i < this.chain.length; i++) {
            if (this.chain[i] === name) {
                return true;
            }
        }
        return false;
    };

    ChainBuilder.prototype.addTask = function(name) {
        if (!name || this._wouldCreateCycle(name)) {
            return;
        }
        this.chain.push(name);
        this._render();
    };

    ChainBuilder.prototype.removeTask = function(name) {
        this.chain = this.chain.filter(function(n) {
            return n !== name;
        });
        this._render();
    };

    ChainBuilder.prototype._render = function() {
        this.$sequence.empty();
        for (var i = 0; i < this.chain.length; i++) {
            var name = this.chain[i];
            var $item = $('<div class="chain-item">').attr('data-task-name', name);
            var $chip = $('<span class="chain-chip">');
            $chip.append($('<span class="chain-chip-label">').text(name));
            var $removeBtn = $('<button type="button" class="chain-chip-remove">')
                .append('<span class="material-symbols-outlined">close</span>');
            $chip.append($removeBtn);
            $item.append($chip);
            $item.append('<span class="chain-arrow material-symbols-outlined">arrow_forward</span>');
            $item.data('task-name', name);
            this.$sequence.append($item);
        }
        this._updateSelect();
        this._updateHiddenInputs();
        this.$chainOptions.toggle(this.chain.length > 0);
    };

    ChainBuilder.prototype._updateSelect = function() {
        var self = this;
        this.$select.find('option').each(function() {
            var val = $(this).val();
            if (!val) return;
            $(this).prop('disabled', self._wouldCreateCycle(val));
        });
        this.$select.val('');
    };

    ChainBuilder.prototype._updateHiddenInputs = function() {
        var $form = $('#' + this.formId);
        var failureName = this.inputName.replace('chain_task_names', 'chain_on_failure');
        $form.find('input[name="' + this.inputName + '"]').remove();
        $form.find('input[name="' + failureName + '"]').remove();

        if (this.chain.length > 0) {
            for (var i = 0; i < this.chain.length; i++) {
                $('<input>', {
                    type: 'hidden',
                    name: this.inputName,
                    value: this.chain[i]
                }).appendTo($form);
            }
            $('<input>', {
                type: 'hidden',
                name: failureName,
                value: this.chainOnFailure ? 'true' : 'false'
            }).appendTo($form);
        }
    };

    ChainBuilder.prototype._bindEvents = function() {
        var self = this;

        this.$select.on('change', function() {
            var val = $(this).val();
            if (val) {
                self.addTask(val);
            }
        });

        this.$sequence.on('click', '.chain-chip-remove', function(e) {
            e.preventDefault();
            var name = $(this).closest('.chain-item').data('task-name');
            self.removeTask(name);
        });

        this.$chainOnFailureCheckbox.on('change', function() {
            self.chainOnFailure = $(this).is(':checked');
            self._updateHiddenInputs();
        });

        if (this.chainOnFailure) {
            this.$chainOnFailureCheckbox.prop('checked', true);
        }
    };

    ChainBuilder.prototype.getChain = function() {
        return this.chain.slice();
    };

    ChainBuilder.prototype.setTaskName = function(name) {
        this.taskName = name;
        this._updateSelect();
    };

    ChainBuilder.prototype.getChainOnFailure = function() {
        return this.chainOnFailure;
    };

    ChainBuilder.prototype.getChainJSON = function() {
        return JSON.stringify(this.chain);
    };

    // Auto-initialize chain builders on page load
    $('.chain-builder').each(function() {
        var $el = $(this);
        if (!$el.data('chain-builder-instance')) {
            var instance = new ChainBuilder($el, {});
            $el.data('chain-builder-instance', instance);
        }
    });
});
