(function () {
  function initUKCMNav() {
    const hamburger = document.getElementById('hamburger');
    const nav = document.getElementById('mainNav');
    if (!hamburger || !nav || nav.dataset.ukcmNavReady === 'true') return;

    nav.dataset.ukcmNavReady = 'true';
    hamburger.setAttribute('aria-controls', 'mainNav');
    hamburger.setAttribute('aria-expanded', 'false');

    const dropdown = nav.querySelector('.region-nav');
    const dropdownToggle = nav.querySelector('.nav-dropdown-toggle');

    function closeDropdown() {
      if (!dropdown || !dropdownToggle) return;
      dropdown.classList.remove('open');
      dropdownToggle.setAttribute('aria-expanded', 'false');
    }

    function closeNav() {
      nav.classList.remove('nav-open');
      hamburger.setAttribute('aria-expanded', 'false');
      closeDropdown();
    }

    hamburger.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (event.stopImmediatePropagation) event.stopImmediatePropagation();

      const isOpen = nav.classList.toggle('nav-open');
      hamburger.setAttribute('aria-expanded', String(isOpen));
      if (!isOpen) closeDropdown();
    }, true);

    if (dropdown && dropdownToggle) {
      dropdownToggle.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        const isOpen = dropdown.classList.toggle('open');
        dropdownToggle.setAttribute('aria-expanded', String(isOpen));
      });

      dropdown.addEventListener('click', function (event) {
        event.stopPropagation();
      });
    }

    nav.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', closeNav);
    });

    document.addEventListener('click', function (event) {
      const clickedInsideNav = nav.contains(event.target);
      const clickedHamburger = hamburger.contains(event.target);
      if (!clickedInsideNav && !clickedHamburger) closeNav();
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeNav();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUKCMNav);
  } else {
    initUKCMNav();
  }
})();
