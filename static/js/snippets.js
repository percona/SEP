$(document).ready(function() {
    $('.downloadSnippetForm').submit(function(e) {
        e.preventDefault();
        const anchorTag = $(this).siblings("a.downloadSnippet")[0];
        anchorTag.click();
    });
});
