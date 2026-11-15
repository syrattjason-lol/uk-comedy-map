/* ---------- GET VENUE SLUG ---------- */

const slug = window.location.pathname
.split("/")
.pop()
.replace(".html","");

/* ---------- LOAD DATA ---------- */

Promise.all([
fetch("/data/venues.json").then(r=>r.json()),
fetch("/data/shows.json").then(r=>r.json()),
fetch("/data/clubs.json").then(r=>r.json())
])

.then(([venues,shows,clubs])=>{

const venue = venues.find(v => v.slug === slug);

if(!venue) return;

/* ---------- VENUE DETAILS ---------- */

const nameEl = document.getElementById("venueName");
const addressEl = document.getElementById("venueAddress");

if(nameEl) nameEl.textContent = venue.name;

if(addressEl){
addressEl.textContent =
venue.street + ", " + venue.city;
}

const container = document.getElementById("venueShows");

if(!container) return;

/* ---------- MATCH SHOWS ---------- */

const venueShows = shows.filter(show =>
show.venueSlug === venue.slug
);

/* ---------- MATCH CLUB NIGHTS ---------- */

const venueClubs = clubs.filter(club =>
club.venueSlug === venue.slug
);

/* ---------- COMBINE LISTINGS ---------- */

const listings = [

...venueClubs.map(club => ({
comedian: club.name,
venue: club.venue,
date: club.schedule,
tickets: club.tickets,
image: club.image
})),

...venueShows

];

/* ---------- RENDER CARDS ---------- */

listings.forEach(item => {

const card = document.createElement("article");

card.className = "show-card";

card.innerHTML = `

<div class="show-image">
<img src="${item.image}" alt="${item.comedian}">
</div>

<div class="show-card-content">

<h3>${item.comedian}</h3>

<p class="venue">${item.venue}</p>

<p class="meta">📅 ${item.date}</p>

<a class="ticket-btn" href="${item.tickets}" target="_blank">
Tickets
</a>

</div>

`;

container.appendChild(card);

});

})
.catch(err => {

const container = document.getElementById("venueShows");

if(container){
container.innerHTML =
'<div class="empty-state">Could not load venue listings.</div>';
}

});