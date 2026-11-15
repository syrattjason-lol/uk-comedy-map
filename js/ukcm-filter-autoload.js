(function () {
  function revealAndTriggerAllFilter() {
    var resultsWrap = document.querySelector('.home-search-results-wrap');
    if (resultsWrap) {
      resultsWrap.classList.add('home-search-active');
    }

    var attempts = 0;
    var maxAttempts = 20;

    var timer = window.setInterval(function () {
      attempts += 1;

      var allButton = document.querySelector('[data-show-filter="all"]');
      var showsGrid = document.getElementById('shows');

      if (allButton && showsGrid) {
        allButton.click();
        window.clearInterval(timer);
        return;
      }

      if (attempts >= maxAttempts) {
        window.clearInterval(timer);
      }
    }, 250);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', revealAndTriggerAllFilter);
  } else {
    revealAndTriggerAllFilter();
  }
})();
