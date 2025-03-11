$(document).ready(function() {
    $('.downloadSnippetForm').submit(function(e) {
        e.preventDefault();
        const anchorTag = $(this).siblings('a.downloadSnippet')[0];
        anchorTag.click();
    });

    $('a.downloadSnippet').click(function() {
        const $anchor = $(this);
        const snippetFilename = $.escapeSelector($anchor.data('snippet-filename'));
        const $approveButton = $(`#${snippetFilename}-approval > button[type=submit]:is([disabled])`);
        $approveButton.prop("disabled", false);
        $approveButton.attr("title", $approveButton.data("next-title"));
    })
});
