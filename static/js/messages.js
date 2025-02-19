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
