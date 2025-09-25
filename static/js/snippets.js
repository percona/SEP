$(document).ready(function() {
    $('a.downloadSnippet').click(function() {
        const $anchor = $(this);
        const snippetFilename = $.escapeSelector($anchor.data('snippet-filename'));
        const $approveButton = $(`#${snippetFilename}-approval > button[type=submit]:is([disabled])`);
        $approveButton.prop("disabled", false);
        $approveButton.attr("title", $approveButton.data("next-title"));
    })
});
