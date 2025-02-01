function humanizeRelativeTime(date) {
    const now = Date.now();
    const diff = date.getTime() - now;
    const seconds = Math.abs(diff / 1000);

    const minute = 60;
    const hour = 60 * minute;
    const day = 24 * hour;

    let relativeTime = "";

    if (seconds <= 44) {
        relativeTime = "a few seconds";
    } else if (seconds <= 89) {
        relativeTime = "a minute";
    } else if (seconds <= 44 * minute) {
        const minutes = Math.round(seconds / minute);
        relativeTime = `${minutes} minutes`;
    } else if (seconds <= 89 * minute) {
        relativeTime = "an hour";
    } else if (seconds <= 21 * hour) {
        const hours = Math.round(seconds / hour);
        relativeTime = `${hours} hours`;
    } else if (seconds <= 35 * hour) {
        relativeTime = "a day";
    } else if (seconds <= 25 * day) {
        const days = Math.round(seconds / day);
        relativeTime = `${days} days`;
    } else if (seconds <= 45 * day) {
        relativeTime = "a month";
    } else if (seconds <= 319 * day) {
        let months = Math.round(seconds / (30 * day));
        months = Math.min(Math.max(months, 2), 10);
        relativeTime = `${months} months`;
    } else if (seconds <= 547 * day) {
        relativeTime = "a year";
    } else {
        const years = Math.round(seconds / (365 * day));
        relativeTime = `${years} years`;
    }

    return diff > 0 ? `in ${relativeTime}` : `${relativeTime} ago`;
}

$(document).ready(function () {
    $('.relativeTime').each(function () {
        const $dateElem = $(this);
        const relativeDate = new Date($(this).text());
        $dateElem.attr('title', humanizeRelativeTime(relativeDate));
    });
});
