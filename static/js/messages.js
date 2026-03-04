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

$(function() {
    $('.close-button').click(function() {
        const $msg = $(this).closest('.message');
        $msg.off();
        $msg.fadeOut(500, function() {
            $msg.remove();
        });
    });

    const timers = {
        'info': 10000,
        'success': 10000,
        'warning': 20000,
        'error': 30000
    };

    const messages = $('#messages .message:not(.sticky)');
    messages.each(function() {
        const $msg = $(this);
        const level = $msg.data('level') || 'info';
        $msg.data('timeoutId', setTimeout(function() {
            $msg.fadeOut(1000, function() {
                $(this).remove();
            });
        }, timers[level]));
    });

    messages.hover(function() {
        const $msg = $(this);
        $msg.stop().animate({
            opacity: '100'
        });
        clearTimeout($msg.data('timeoutId'));
    }, function() {
        const $msg = $(this);
        const level = $msg.data('level') || 'info';
        $msg.data('timeoutId', setTimeout(function() {
            $msg.fadeOut(1000, function() {
                $(this).remove();
            });
        }, timers[level]));
    });
});
