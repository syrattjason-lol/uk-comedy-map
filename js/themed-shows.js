(() => {
  "use strict";

  const root = document.querySelector("[data-themed-shows]");
  if (!root) return;

  const mode = (root.dataset.filterMode || "all").toLowerCase();
  const city = normalise(root.dataset.filterCity || "");
  const venueTerms = splitTerms(root.dataset.filterVenue || "");
  const limit = Number(root.dataset.showLimit || 24);
  const feedUrl = root.dataset.feedUrl || "/data/shows.json";
  const emptyText = root.dataset.emptyText || "No matching upcoming shows are available at the moment.";

  const grid = root.querySelector(".themed-show-grid");
  const status = root.querySelector(".themed-show-status");
  const moreButton = root.querySelector(".themed-load-more");
  let matches = [];
  let visible = Math.min(12, limit);

  function normalise(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/&amp;/g, "&")
      .replace(/[’‘]/g, "'")
      .replace(/\s+/g, " ")
      .trim();
  }

  function splitTerms(value) {
    return String(value || "")
      .split("|")
      .map(normalise)
      .filter(Boolean);
  }

  function textFor(show) {
    return normalise([
      show.comedian, show.title, show.name, show.event,
      show.venue, show.city, show.state, show.region,
      show.category, show.type, show.description,
      show.price, show.cost, show.tags, show.source
    ].filter(Boolean).join(" "));
  }

  function parsePrice(show) {
    const raw = normalise(show.price || show.cost || show.ticket_price || "");
    if (!raw) return null;
    if (/\bfree\b|£\s*0(?:\.00)?\b|0\s*gbp\b/.test(raw)) return 0;
    const match = raw.match(/£\s*(\d+(?:\.\d{1,2})?)/);
    return match ? Number(match[1]) : null;
  }

  function parseDate(show) {
    const raw = show.date || show.start_date || show.datetime || show.start || "";
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function isUpcoming(show) {
    const date = parseDate(show);
    if (!date) return true;
    const today = new Date();
    today.setHours(0,0,0,0);
    return date >= today;
  }

  function isWeekend(show) {
    const date = parseDate(show);
    if (!date) return false;
    const now = new Date();
    now.setHours(0,0,0,0);
    const day = now.getDay();
    const daysUntilFriday = (5 - day + 7) % 7;
    const friday = new Date(now);
    friday.setDate(now.getDate() + daysUntilFriday);
    const sunday = new Date(friday);
    sunday.setDate(friday.getDate() + 2);
    sunday.setHours(23,59,59,999);
    return date >= friday && date <= sunday;
  }

  function cityMatches(show) {
    if (!city) return true;
    return normalise(show.city || show.location || "").includes(city) ||
           textFor(show).includes(city);
  }

  function venueMatches(show) {
    if (!venueTerms.length) return true;
    const venue = normalise(show.venue || "");
    const all = textFor(show);
    return venueTerms.some(term => venue.includes(term) || all.includes(term));
  }

  function modeMatches(show) {
    const text = textFor(show);
    const price = parsePrice(show);

    switch (mode) {
      case "free":
        return price === 0 ||
          /\bfree entry\b|\bfree comedy\b|\bpay what you want\b|\bpay-what-you-want\b|\bdonation\b/.test(text);

      case "open-mic":
      case "openmic":
        return /\bopen mic\b|\bnew act\b|\bnew acts\b|\bnew material\b|\bnew comedian\b|\bnew comedians\b|\bwork in progress\b|\bwip\b/.test(text);

      case "weekend":
        return isWeekend(show);

      case "festival":
      case "festivals":
        return /\bfestival\b|\bfringe\b/.test(text);

      case "tour":
      case "touring":
        return /\btour\b|\btouring\b|\btheatre\b|\barena\b|\blive at\b/.test(text) &&
               !/\bopen mic\b|\bnew material\b/.test(text);

      case "famous-clubs":
        return [
          "the comedy store", "comedy store",
          "frog & bucket", "frog and bucket",
          "top secret comedy club", "top secret",
          "angel comedy", "backyard comedy club",
          "komedia", "the glee", "glee club",
          "hot water comedy club", "monkey barrel",
          "just the tonic", "pleasance"
        ].some(term => text.includes(term));

      case "cities":
        return Boolean(show.city) && isUpcoming(show);

      case "venue":
      case "venue-auto":
        return venueMatches(show);

      case "all":
      default:
        return true;
    }
  }

  function matchesFilter(show) {
    return isUpcoming(show) &&
      cityMatches(show) &&
      venueMatches(show) &&
      modeMatches(show);
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, char => ({
      "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;"
    })[char]);
  }

  function formatDate(show) {
    const date = parseDate(show);
    if (!date) return escapeHtml(show.date || "");
    return new Intl.DateTimeFormat("en-GB", {
      weekday: "short", day: "numeric", month: "short", year: "numeric"
    }).format(date);
  }

  function imageFor(show) {
    return show.image || show.image_url || show.poster || show.thumbnail || "/images/comedy-placeholder.jpg";
  }

  function ticketFor(show) {
    return show.tickets || show.ticket_url || show.url || show.link || "#";
  }

  function titleFor(show) {
    return show.comedian || show.title || show.name || show.event || "Comedy show";
  }

  function displayTicketPrice(value) {
    const raw = String(value ?? '').trim();
    if (!raw) return '';
    if (/^free$/i.test(raw)) return 'Free';
    const amounts = [...raw.matchAll(/£\s*(\d[\d,]*(?:\.\d{1,2})?)/g)]
      .map(match => Number(match[1].replace(/,/g, '')))
      .filter(Number.isFinite);
    if (amounts.length < 2) return raw;
    const max = Math.max(...amounts);
    return '£' + (Number.isInteger(max) ? String(max) : max.toFixed(2))
      + (/booking fee/i.test(raw) ? ' + booking fee' : '');
  }

  function renderCard(show) {
    const title = escapeHtml(titleFor(show));
    const venue = escapeHtml(show.venue || "");
    const location = escapeHtml([show.city, show.state].filter(Boolean).join(", "));
    const date = formatDate(show);
    const time = escapeHtml(show.time || show.start_time || "");
    const price = escapeHtml(displayTicketPrice(show.price ?? show.cost ?? show.ticket_price));
    const ticket = escapeHtml(ticketFor(show));
    const image = escapeHtml(imageFor(show));

    return `
      <article class="show-card themed-show-card">
        <img class="show-image" src="${image}" alt="${title}" loading="lazy"
             onerror="this.onerror=null;this.src='/images/comedy-placeholder.jpg';">
        <div class="show-card-content">
          <h3>${title}</h3>
          ${venue ? `<p class="show-venue"><strong>${venue}</strong></p>` : ""}
          ${location ? `<p>${location}</p>` : ""}
          ${date ? `<p>${date}${time ? ` · ${time}` : ""}</p>` : ""}
          ${price ? `<p class="show-price">${price}</p>` : ""}
          <a class="ticket-btn" href="${ticket}" target="_blank" rel="noopener">View tickets</a>
        </div>
      </article>`;
  }

  function render() {
    const shown = matches.slice(0, Math.min(visible, limit));
    grid.innerHTML = shown.map(renderCard).join("");

    if (!matches.length) {
      status.textContent = emptyText;
      status.hidden = false;
    } else {
      status.textContent = `${matches.length} matching upcoming ${matches.length === 1 ? "show" : "shows"}`;
      status.hidden = false;
    }

    moreButton.hidden = shown.length >= Math.min(matches.length, limit);
  }

  moreButton?.addEventListener("click", () => {
    visible += 12;
    render();
  });

  status.textContent = "Loading matching comedy shows…";
  status.hidden = false;

  fetch(feedUrl, { cache: "no-store" })
    .then(response => {
      if (!response.ok) throw new Error(`Feed returned ${response.status}`);
      return response.json();
    })
    .then(data => {
      const shows = Array.isArray(data) ? data :
        Array.isArray(data.shows) ? data.shows :
        Array.isArray(data.events) ? data.events : [];

      matches = shows
        .filter(show => show && typeof show === "object")
        .filter(matchesFilter)
        .sort((a, b) => {
          const da = parseDate(a);
          const db = parseDate(b);
          if (!da && !db) return 0;
          if (!da) return 1;
          if (!db) return -1;
          return da - db;
        });

      render();
    })
    .catch(error => {
      console.error("Themed shows error:", error);
      status.textContent = "Comedy listings could not be loaded right now.";
      status.hidden = false;
      moreButton.hidden = true;
    });
})();