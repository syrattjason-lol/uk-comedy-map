const path = window.location.pathname.toLowerCase();


const REGION_SLUG_LOOKUP = {
  "east-midlands": "East Midlands",
  "east-of-england": "East of England",
  "london": "London",
  "north-east": "North East",
  "north-west": "North West",
  "northern-ireland": "Northern Ireland",
  "scotland": "Scotland",
  "south-east": "South East",
  "south-west": "South West",
  "wales": "Wales",
  "west-midlands": "West Midlands",
  "yorkshire": "Yorkshire"
};
const CITY_REGION_LOOKUP = {
  "thurso": "Scotland",
  "wick": "Scotland",
  "aberdeen": "Scotland",
  "stornoway": "Scotland",
  "penzance": "South West",
  "helston": "South West",
  "scarborough": "Yorkshire",
  "hull": "Yorkshire",
  "newcastle upon tyne": "North East",
  "whitby": "Yorkshire",
  "sheffield": "Yorkshire",
  "gateshead": "North East",
  "york": "Yorkshire",
  "leeds": "Yorkshire",
  "middlesbrough": "North East",
  "sunderland": "North East",
  "grantham": "East Midlands",
  "manchester": "North West",
  "belfast": "Northern Ireland",
  "portrush": "Northern Ireland",
  "dukinfield": "North West",
  "leamington spa": "West Midlands",
  "port glasgow": "Scotland",
  "greenock": "Scotland",
  "londonderry": "Northern Ireland",
  "larne": "Northern Ireland",
  "edinburgh": "Scotland",
  "london": "London",
  "oxford": "South East",
  "folkestone": "South East",
  "kingston upon thames": "London",
  "omagh": "Northern Ireland",
  "ripon": "Yorkshire",
  "luton": "East of England",
  "bournemouth": "South West",
  "alnwick": "North East",
  "morpeth": "North East",
  "falmouth": "South West",
  "torquay": "South West",
  "plymouth": "South West",
  "redruth": "South West",
  "saint austell": "South West",
  "exeter": "South West",
  "holsworthy": "South West",
  "inverurie": "Scotland",
  "banchory": "Scotland",
  "peterhead": "Scotland",
  "ellon": "Scotland",
  "ramsgate": "South East",
  "margate": "South East",
  "dover": "South East",
  "deal": "South East",
  "broadstairs": "South East",
  "birchington": "South East",
  "sandwich": "South East",
  "canterbury": "South East",
  "herne bay": "South East",
  "whitstable": "South East",
  "hythe": "South East",
  "blyth": "North East",
  "horndean": "South East",
  "southampton": "South East",
  "portsmouth": "South East",
  "ringwood": "South West",
  "ferndown": "South West",
  "poole": "South West",
  "salisbury": "South West",
  "southsea": "South East",
  "fareham": "South East",
  "liss": "South East",
  "hayling island": "South East",
  "midhurst": "South East",
  "petworth": "South East",
  "bognor regis": "South East",
  "arundel": "South East",
  "chichester": "South East",
  "fordingbridge": "South East",
  "alresford": "South East",
  "gosport": "South East",
  "ventnor": "South East",
  "ryde": "South East",
  "winchester": "South East",
  "shanklin": "South East",
  "lymington": "South East",
  "newport": "Wales",
  "romsey": "South East",
  "wimborne": "South West",
  "sandown": "South East",
  "eastleigh": "South East",
  "haslemere": "South East",
  "new milton": "South East",
  "bordon": "South East",
  "hampshire": "South East",
  "blandford forum": "South West",
  "petersfield": "South East",
  "gillingham": "South West",
  "havant": "South East",
  "wareham": "South West",
  "newry": "Northern Ireland",
  "armagh": "Northern Ireland",
  "newcastle": "North East",
  "banbridge": "Northern Ireland",
  "downpatrick": "Northern Ireland",
  "waterlooville": "South East",
  "alton": "South East",
  "ballymena": "Northern Ireland",
  "ballymoney": "Northern Ireland",
  "coleraine": "Northern Ireland",
  "limavady": "Northern Ireland",
  "bangor": "Northern Ireland",
  "craigavon": "Northern Ireland",
  "newtownards": "Northern Ireland",
  "maghera": "Northern Ireland",
  "ballycastle": "Northern Ireland",
  "inverness": "Scotland",
  "muir of ord": "Scotland",
  "nairn": "Scotland",
  "elgin": "Scotland",
  "buckie": "Scotland",
  "strathpeffer": "Scotland",
  "orkney": "Scotland",
  "stromness": "Scotland",
  "newmarket": "East of England",
  "chesterfield": "East Midlands",
  "portree": "Scotland",
  "dungannon": "Northern Ireland",
  "newtownabbey": "Northern Ireland",
  "antrim": "Northern Ireland",
  "kirkwall": "Scotland",
  "carlisle": "North West",
  "dumfries": "Scotland",
  "wigton": "North West",
  "langholm": "Scotland",
  "glasgow": "Scotland",
  "south shields": "North East",
  "dunoon": "Scotland",
  "largs": "Scotland",
  "ayr": "Scotland",
  "gourock": "Scotland",
  "west kilbride": "Scotland",
  "saltcoats": "Scotland",
  "helensburgh": "Scotland",
  "troon": "Scotland",
  "kilmarnock": "Scotland",
  "prestwick": "Scotland",
  "strabane": "Northern Ireland",
  "enniskillen": "Northern Ireland",
  "bristol": "South West",
  "chester": "North West",
  "deeside": "Wales",
  "northwich": "North West",
  "oswestry": "West Midlands",
  "llangollen": "Wales",
  "shrewsbury": "West Midlands",
  "telford": "West Midlands",
  "wrexham": "Wales",
  "ellesmere port": "North West",
  "winsford": "North West",
  "market drayton": "West Midlands",
  "crewe": "North West",
  "rhyl": "Wales",
  "millom": "North West",
  "blackpool": "North West",
  "liverpool": "North West",
  "ulverston": "North West",
  "southport": "North West",
  "lancaster": "North West",
  "stoke-on-trent": "West Midlands",
  "stafford": "West Midlands",
  "lichfield": "West Midlands",
  "barrow-in-furness": "North West",
  "stockport": "North West",
  "cookstown": "Northern Ireland",
  "stone": "West Midlands",
  "mold": "Wales",
  "macclesfield": "North West",
  "denbigh": "Wales",
  "middlewich": "North West",
  "abergele": "Wales",
  "nottingham": "East Midlands",
  "lincoln": "East Midlands",
  "melton mowbray": "East Midlands",
  "spalding": "East Midlands",
  "southwell": "East Midlands",
  "boston": "East Midlands",
  "leicester": "East Midlands",
  "sandbach": "North West",
  "frodsham": "North West",
  "colwyn bay": "Wales",
  "congleton": "North West",
  "holywell": "Wales",
  "pant": "West Midlands",
  "nantwich": "North West",
  "poulton-le-fylde": "North West",
  "lytham saint annes": "North West",
  "ruthin": "Wales",
  "lockerbie": "Scotland",
  "staffordshire": "West Midlands",
  "ashby-de-la-zouch": "East Midlands",
  "derby": "East Midlands",
  "belper": "East Midlands",
  "newquay": "South West",
  "truro": "South West",
  "healeys": "South West",
  "neston": "North West",
  "tavistock": "South West",
  "launceston": "South West",
  "ivybridge": "South West",
  "penryn": "South West",
  "fowey": "South West",
  "bodmin": "South West",
  "thornton-cleveleys": "North West",
  "kingsbridge": "South West",
  "saltash": "South West",
  "lifto": "South West",
  "torpoint": "South West",
  "caernarfon": "Wales",
  "calstock": "South West",
  "salcombe": "South West",
  "coalville": "East Midlands",
  "skegness": "East Midlands",
  "fleetwood": "North West",
  "lancashire": "North West",
  "stamford": "East Midlands",
  "lisburn": "Northern Ireland",
  "ludlow": "West Midlands",
  "builth wells": "Wales",
  "bromyard": "West Midlands",
  "llandrindod wells": "Wales",
  "much wenlock": "West Midlands",
  "newtown": "Wales",
  "llanidloes": "Wales",
  "castle douglas": "Scotland",
  "stranraer": "Scotland",
  "cumnock": "Scotland",
  "maybole": "Scotland",
  "stourbridge": "West Midlands",
  "worcester": "West Midlands",
  "wolverhampton": "West Midlands",
  "bridgnorth": "West Midlands",
  "stourport-on-severn": "West Midlands",
  "worcestershire": "West Midlands",
  "brierley hill": "West Midlands",
  "machynlleth": "Wales",
  "kidderminster": "West Midlands",
  "bewdley": "West Midlands",
  "holywood": "Northern Ireland",
  "dudley": "West Midlands",
  "bath": "South West",
  "faringdon": "South East",
  "weston-super-mare": "South West",
  "clevedon": "South West",
  "newbury": "South East",
  "swindon": "South West",
  "bridgwater": "South West",
  "frome": "South West",
  "cheddar": "South West",
  "warminster": "South West",
  "andover": "South East",
  "burnham-on-sea": "South West",
  "devizes": "South West",
  "street": "South West",
  "pontypool": "Wales",
  "hungerford": "South East",
  "melksham": "South West",
  "corsham": "South West",
  "wantage": "South East",
  "wells": "South West",
  "glastonbury": "South West",
  "chippenham": "South West",
  "wedmore": "South West",
  "clydebank": "Scotland",
  "dursley": "South West",
  "rayleigh": "East of England",
  "alcester": "West Midlands",
  "cirencester": "South West",
  "cheltenham": "South West",
  "stratford-upon-avon": "West Midlands",
  "evesham": "West Midlands",
  "stonehouse": "South West",
  "bury saint edmunds": "East of England",
  "norwich": "East of England",
  "thetford": "East of England",
  "diss": "East of England",
  "witney": "South East",
  "chipping norton": "South East",
  "hereford": "West Midlands",
  "cwmbran": "Wales",
  "abergavenny": "Wales",
  "stirling": "Scotland",
  "falkirk": "Scotland",
  "malvern": "West Midlands",
  "gloucester": "South West",
  "banbury": "South East",
  "tewkesbury": "South West",
  "oban": "Scotland",
  "ross-on-wye": "West Midlands",
  "monmouth": "Wales",
  "crickhowell": "Wales",
  "abertillery": "Wales",
  "cambridge": "East of England",
  "king's lynn": "East of England",
  "southwold": "East of England",
  "ely": "East of England",
  "lowestoft": "East of England",
  "moreton-in-marsh": "South West",
  "abingdon": "South East",
  "chepstow": "Wales",
  "warwick": "West Midlands",
  "teignmouth": "South West",
  "brixham": "South West",
  "dartmouth": "South West",
  "paignton": "South West",
  "weymouth": "South West",
  "budleigh salterton": "South West",
  "newton abbot": "South West",
  "stowmarket": "East of England",
  "great yarmouth": "East of England",
  "saxmundham": "East of England",
  "attleborough": "East of England",
  "beccles": "East of England",
  "wallington": "London",
  "milford haven": "Wales",
  "narberth": "Wales",
  "cardigan": "Wales",
  "ipswich": "East of England",
  "woolpit": "East of England",
  "aldeburgh": "East of England",
  "stroud": "South West",
  "swansea": "Wales",
  "ilfracombe": "South West",
  "aviemore": "Scotland",
  "swaffham": "East of England",
  "stapleford": "East Midlands",
  "memorial": "South East",
  "galashiels": "Scotland",
  "biggar": "Scotland",
  "livingston": "Scotland",
  "dereham": "East of England",
  "fort william": "Scotland",
  "hawick": "Scotland",
  "carluke": "Scotland",
  "birmingham": "West Midlands",
  "newcastle-under-lyme": "West Midlands"
};

function normaliseSlug(value){
  return String(value || '')
    .toLowerCase()
    .replace(/%20/g, '-')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function getRegionFromPath(){
  const parts = path.split('/').filter(Boolean);
  const last = normaliseSlug(parts[parts.length - 1] || '');
  return REGION_SLUG_LOOKUP[last] || null;
}

function getShowRegion(show){
  const explicit = String(show.state || show.region || '').trim();
  if (explicit) return explicit;
  const city = String(show.city || '').trim().toLowerCase();
  return CITY_REGION_LOOKUP[city] || '';
}

function matchesLocation(show){
  if (cityFilter) return show.city === cityFilter;
  if (regionFilter) return getShowRegion(show) === regionFilter;
  return true;
}

function clubMatchesLocation(club){
  if (cityFilter) return club.city === cityFilter;
  if (regionFilter) return getShowRegion(club) === regionFilter;
  return true;
}

let cityFilter = null;
if (path.includes('/comedy-shows/london')) cityFilter = 'London';
if (path.includes('/comedy-shows/manchester')) cityFilter = 'Manchester';
if (path.includes('/comedy-shows/leeds')) cityFilter = 'Leeds';
if (path.includes('/comedy-shows/birmingham')) cityFilter = 'Birmingham';
if (path.includes('/comedy-shows/bristol')) cityFilter = 'Bristol';

let regionFilter = cityFilter ? null : getRegionFromPath();

const PER_PAGE = 12;
const DEFAULT_INITIAL_SHOWS = (cityFilter || regionFilter) ? 8 : 20;

let currentIndex = 0;
let shows = [];
let activeFilter = 'all';
let activeSearch = '';
let venueCounts = {};

const venueDescriptions = {
  'Top Secret Comedy Club': `One of London's busiest stand-up venues, hosting professional comedians and Edinburgh Fringe previews throughout the year.`,
  'Angel Comedy': 'A legendary free-entry comedy venue known for discovering new talent and hosting TV comedians.',
  'Comedy Store': `The UK's most famous comedy club and home of The Comedy Store Players improv show.`,
  'The Comedy Store': `The UK's most famous comedy club and home of The Comedy Store Players improv show.`,
  'Frog & Bucket': `One of Manchester's longest-running comedy clubs, famous for its weekly Beat The Frog new act competition.`,
  'The Comedy Store Manchester': 'Hosts major touring comedians and regular weekend showcase lineups.',
  'Lions Den': 'An intimate city-centre venue featuring independent comedy nights and touring acts.',
  'Lions Den Manchester': 'An intimate city-centre venue featuring independent comedy nights and touring acts.',
  'Glee Club': `Birmingham's best-known comedy venue featuring household names and rising stars every week.`,
  'Just The Tonic': 'Popular for affordable comedy nights and mixed-bill stand-up showcases.',
  'The Old Joint Stock': 'A characterful pub theatre combining comedy, live entertainment and food in the city centre.',
  'The Comedy Box': 'Regularly attracts nationally recognised comedians and Edinburgh Fringe previews.',
  'Smoke & Mirrors': 'Combines close-up magic, comedy and cabaret in a unique venue setting.',
  'The Wardrobe Theatre': 'Known for alternative comedy, sketch shows and creative live performances.',
  'The HiFi Club': `One of the North's most established comedy venues with weekly professional stand-up lineups.`,
  'Comedy Club at HIFI': `One of the North's most established comedy venues with weekly professional stand-up lineups.`,
  'The Wardrobe': 'Hosts comedy, live music and touring performances in a relaxed city-centre setting.',
  'Seven Arts': 'A popular venue for fringe comedy, work-in-progress shows and local talent.'
};

function getVenueDescription(show){
  const venue = String(show.venue || '').trim();
  const city = String(show.city || '').trim();
  return venueDescriptions[venue] || `${city} comedy venue with upcoming listings on UK Comedy Map. Check this venue for regular stand-up nights, touring acts and local comedy events.`;
}


function escapeHtml(value){
  return String(value || '').replace(/[&<>"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));
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

function cleanImage(image){
  const value = String(image || '').trim();
  if (!value) return '/images/default-comedy.jpg';
  if (value.startsWith('http') || value.startsWith('data:image')) return value;
  const match = value.match(/https?:\/\/[^'"} ]+/);
  return match ? match[0] : '/images/default-comedy.jpg';
}

function isFutureOrToday(dateString){
  if(!dateString) return false;
  const dateOnly = String(dateString).split('T')[0];
  const eventDate = new Date(dateOnly);
  if (Number.isNaN(eventDate.getTime())) return false;
  const today = new Date();
  today.setHours(0,0,0,0);
  eventDate.setHours(0,0,0,0);
  return eventDate >= today;
}

function isWeekend(dateString){
  const date = new Date(String(dateString || '').split('T')[0]);
  if (Number.isNaN(date.getTime())) return false;
  return [0,5,6].includes(date.getDay());
}

function isCheapShow(show){
  const text = `${show.comedian || ''} ${show.venue || ''} ${show.tickets || ''} ${show.type || ''}`.toLowerCase();
  return text.includes('free') || text.includes('cheap') || text.includes('open mic') || text.includes('pay what') || text.includes('£0') || text.includes('student');
}

function isPopularShow(show){
  return (venueCounts[show.venue] || 0) > 1;
}

function filterShows(){
  let output = shows.slice();
  if (activeSearch) {
    output = output.filter(show => `${show.comedian || ''} ${show.venue || ''} ${show.city || ''} ${show.state || ''} ${show.date || ''}`.toLowerCase().includes(activeSearch));
  }
  if (activeFilter === 'featured') output = output.filter(show => show.premium || show.featured || show.type === 'tour');
  if (activeFilter === 'popular') output = output.filter(isPopularShow);
  if (activeFilter === 'weekend') output = output.filter(show => isWeekend(show.date));
  if (activeFilter === 'cheap') output = output.filter(isCheapShow);
  return output;
}

function updateResults(){
  const filtered = filterShows();
  currentIndex = Math.min(DEFAULT_INITIAL_SHOWS, filtered.length);
  renderShows(filtered.slice(0, currentIndex));
  updateLoadButton(filtered.length);
}

Promise.all([
  fetch('/data/clubs.json').then(r => r.ok ? r.json() : [] ).catch(() => []),
  fetch('/data/shows.json').then(r => r.json())
])
.then(([clubs, showsData]) => {
  const container = document.getElementById('shows');
  if(!container) return;

  const premium = (clubs || [])
    .filter(c => c.premium === true)
    .filter(clubMatchesLocation)
    .slice(0,4)
    .map(c => ({
      comedian: c.name,
      venue: c.venue || c.name,
      city: c.city,
      date: c.schedule || 'Featured',
      tickets: c.tickets || c.website || '#',
      image: c.image,
      premium: true,
      featured: true
    }));

  const filteredShows = (showsData || [])
    .filter(matchesLocation)
    .filter(show => show.comedian && show.venue && isFutureOrToday(show.date))
    .sort((a,b) => new Date(a.date) - new Date(b.date));

  shows = [...premium, ...filteredShows];
  venueCounts = shows.reduce((acc, show) => {
    if(show.venue) acc[show.venue] = (acc[show.venue] || 0) + 1;
    return acc;
  }, {});

  renderVenueCards(shows);

  if(!shows.length){
    container.innerHTML = '<div class="empty-state">Could not load show listings.</div>';
    updateLoadButton(0);
    return;
  }

  updateResults();
})
.catch(() => {
  const container = document.getElementById('shows');
  if(container){
    container.innerHTML = '<div class="empty-state">Could not load show listings.</div>';
  }
});

function renderShows(items){
  const container = document.getElementById('shows');
  if(!container) return;
  container.innerHTML = '';

  if(!items.length){
    container.innerHTML = '<div class="empty-state">No matching shows found. Try another filter.</div>';
    return;
  }

  items.forEach(show => {
    const card = document.createElement('article');
    card.className = 'show-card';
    const title = String(show.comedian || 'Comedy show');
    const safeTitle = title.length > 80 ? title.substring(0,80) + '…' : title;
    const dateLabel = show.premium ? show.date : new Date(show.date).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });

    const priceLabel = displayTicketPrice(show.price ?? show.ticket_price ?? show.cost);

    card.innerHTML = `
      <div class="show-image">
        <img src="${cleanImage(show.image)}" loading="lazy" onerror="this.onerror=null;this.src='/images/default-comedy.jpg'" alt="${escapeHtml(title)}">
      </div>
      <div class="show-card-content">
        <h3>${escapeHtml(safeTitle)}</h3>
        <p class="venue">${escapeHtml(show.venue)}</p>
        <p class="meta">📍 ${escapeHtml(show.city)}</p>
        <p class="meta">📅 ${escapeHtml(dateLabel)}</p>
        ${priceLabel ? `<p class="meta show-price">Price: ${escapeHtml(priceLabel)}</p>` : ''}
        <a class="ticket-btn" href="${escapeHtml(show.tickets || '#')}" target="_blank" rel="noopener noreferrer">Tickets</a>
      </div>`;
    container.appendChild(card);
  });
}

function renderVenueCards(allShows){
  const venueContainer = document.getElementById('venueCards');
  if(!venueContainer) return;
  const byVenue = new Map();
  allShows.forEach(show => {
    if(!show.venue || byVenue.has(show.venue)) return;
    byVenue.set(show.venue, show);
  });

  const venues = Array.from(byVenue.values()).slice(0, 6);
  if(!venues.length){
    venueContainer.innerHTML = '<div class="empty-state">Venue guide coming soon.</div>';
    return;
  }

  venueContainer.innerHTML = venues.map(show => `
    <article class="venue-card">
      <div class="venue-thumb"><img src="${cleanImage(show.image)}" loading="lazy" onerror="this.onerror=null;this.src='/images/default-comedy.jpg'" alt="${escapeHtml(show.venue)}"></div>
      <div class="venue-card-content">
        <h3>${escapeHtml(show.venue)}</h3>
        <p>${escapeHtml(getVenueDescription(show))}</p>
        <a href="#shows">See shows</a>
      </div>
    </article>
  `).join('');
}

function updateLoadButton(total){
  const loadBtn = document.getElementById('loadMoreBtn');
  if(!loadBtn) return;
  loadBtn.style.setProperty('display', currentIndex >= total ? 'none' : 'inline-flex', 'important');
}

document.getElementById('loadMoreBtn')?.addEventListener('click', () => {
  const filtered = filterShows();
  currentIndex = Math.min(currentIndex + PER_PAGE, filtered.length);
  renderShows(filtered.slice(0, currentIndex));
  updateLoadButton(filtered.length);
});

document.addEventListener('DOMContentLoaded', function () {
  const hamburger = document.getElementById('hamburger');
  const nav = document.getElementById('mainNav');
  if (hamburger && nav) {
    hamburger.addEventListener('click', function () {
      nav.classList.toggle('nav-open');
    });
  }

  const searchInput = document.getElementById('showSearch');
  if(searchInput){
    searchInput.addEventListener('input', e => {
      activeSearch = e.target.value.trim().toLowerCase();
      updateResults();
    });
  }

  document.querySelectorAll('[data-show-filter]').forEach(button => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.showFilter || 'all';
      document.querySelectorAll('[data-show-filter]').forEach(btn => btn.classList.remove('active'));
      button.classList.add('active');
      updateResults();
    });
  });
});
