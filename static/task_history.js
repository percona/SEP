$(document).ready(function() {
  // Toggle Logs Console Visibility
  $('.logs-button').click(function() {
    var logId = $(this).data('log-id');
    var logRow = $('tr.log-row[data-log-id="' + logId + '"]');
    logRow.toggle();
    var button = $(this);
    if (logRow.is(':visible')) {
      button.text('visibility_off');
    } else {
      button.text('visibility');
    }
  });

  // Handle tab clicks for log type tabs (stdout/stderr)
  $('.log-type-tab').click(function(e) {
    e.preventDefault();
    var $this = $(this);
    var logType = $this.data('log-type');
    var $logConsole = $this.closest('.log-console');

    // Update selected tab
    $this.closest('.log-tabs').find('.log-type-tab').removeClass('selected');
    $this.addClass('selected');

    // Show/hide logs based on selected log type
    $logConsole.find('.log-output').hide();
    $logConsole.find('.log-step-content:visible .log-output[data-log-type="' + logType + '"]').show();
  });

  // Handle tab clicks for step tabs
  $('.log-step-tab').click(function(e) {
    e.preventDefault();
    var $this = $(this);
    var stepName = $this.data('step-name');
    var $logConsole = $this.closest('.log-console');

    // Update selected tab
    $this.closest('.log-tabs').find('.log-step-tab').removeClass('selected');
    $this.addClass('selected');

    // Show/hide steps
    $logConsole.find('.log-step-content').hide();
    $logConsole.find('.log-step-content[data-step-name="' + stepName + '"]').show();

    // Show/hide logs based on selected log type
    var selectedLogType = $logConsole.find('.log-type-tab.selected').data('log-type');
    $logConsole.find('.log-output').hide();
    $logConsole.find('.log-step-content[data-step-name="' + stepName + '"] .log-output[data-log-type="' + selectedLogType + '"]').show();
  });

  // Handle word wrap toggle switch
  $('.word-wrap-checkbox').change(function() {
    var $this = $(this);
    var $logConsole = $this.closest('.log-console');
    if ($this.is(':checked')) {
      $logConsole.find('.log-output').addClass('word-wrap');
    } else {
      $logConsole.find('.log-output').removeClass('word-wrap');
    }
  });
  $('.word-wrap-checkbox').trigger("change");

  $('.toggle-label').click(function(e) {
      $(this).prev(".switch").click();
  });
});
