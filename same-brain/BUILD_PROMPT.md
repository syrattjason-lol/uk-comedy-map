# Copy-and-paste AI build prompt — SAME BRAIN

Build and deliver a COMPLETE, beautiful, responsive, production-conscious multiplayer browser party game named **SAME BRAIN** for my website **https://www.ukcomedymap.co.uk/**. It is inspired by the social mechanic of Herd Mentality, but must use entirely original branding, graphics, copy and questions.

## Experience and purpose

This is a fun, slightly cheeky, highly polished party game in which players try to give the answer they think most other people will give to a subjective question. It must work on each person's own phone without accounts, downloads, payment or sign-up. The host shares a **single private invitation URL** (not a public room directory). Players open the URL, type a nickname and immediately join the same live room. There must be **no artificial player cap**: use scalable per-player records, while clearly explaining that hosting and service quotas impose real limits. Do not fake multiplayer with localStorage, iframes or mock players.

## Architecture (critical)

My existing site can host static HTML/CSS/JavaScript. Provide actual deployable files: `index.html`, `styles.css`, `app.js`, `questions.js`, `config.js`, `firestore.rules`, and `README.md`. Use semantic HTML5, modern vanilla JavaScript, modular Firebase Web SDK, **Firebase Anonymous Authentication and Cloud Firestore with realtime snapshot listeners**. Keep all project configuration in `config.js`. Never include private API keys, admin secrets, service-account credentials or insecure `allow read, write: if true` rules. Include complete Firestore security rules, setup instructions, hosting layout and manual multi-device tests. The game must be functional once I paste my public Firebase web app config, enable Anonymous Authentication and publish the rules. Do not claim a static HTML file alone provides real-time multiplayer.

## Game flow

1. **Landing page:** brand hero, short rules, nickname field, clear "Create private game" action.
2. **Host room:** generate a cryptographically random unguessable room ID and a shareable link, e.g. `https://www.ukcomedymap.co.uk/same-brain/?room=<random-uuid>`. Provide copy and native mobile share buttons. Do not provide a publicly searchable list of rooms.
3. **Join flow:** clicking the link opens a room preview and nickname form; pressing Join enters lobby; no login form or access-code entry required. Host and guests see a live player list with initials avatars and a host badge. People joining late should work.
4. **Start:** only the host starts. All players receive the same selected random question in real time.
5. **Answer:** each person privately enters a short answer (80 characters max) and presses Submit. Show the number of submitted answers live, but DO NOT show other people's text before reveal. Allow answer edits until reveal. Protect submissions in database rules.
6. **Host review:** before revealing, the host can review all submitted answers, correct obvious equivalent variations, and merge groups such as "washing up" and "doing the dishes". Handle case, punctuation and common articles automatically, but let the host override grouping.
7. **Reveal:** host clicks Reveal. Show answer groups with counts and names, highlight the most popular answer(s), award points, show an "Odd One" badge for a single unique answer, celebrate with subtle confetti, and update everyone's scoreboard simultaneously. Score a tied most-popular group if its size is at least two. No points if all answers are unique.
8. **Scoring:** each person choosing a most-popular answer earns one point. If there is exactly one unique response among 3+ submissions, that one player receives the "Odd One" badge, which blocks them from winning until another sole outlier takes it. Make 8 points the default winning target. Include a live leaderboard, a winner screen and host controls for next round and ending the game.
9. **Reliability:** prevent duplicate award operations, handle slow/disconnected phones gracefully, show useful errors, preserve identity when the page refreshes, do not allow guests to act as host, handle duplicate nicknames, empty inputs, no responses, tied responses, and players joining after start. Test across real devices / distinct anonymous identities.

## Visual design

Make it feel like a premium, modern 2026 party game, not a cheap spreadsheet or generic Bootstrap app. Creative direction: rich midnight aubergine background (#171426), lime accents (#D5FF8B), playful coral pink (#FF8EAA), soft violet (#BAABFF), oversized tight `Space Grotesk` headings and readable `DM Sans` body text. Big friendly cards with rounded corners, subtle gradients and animated organic shapes, glassy room panels, custom status chips, progress bars, lively player avatars, confetti on reveal, editorial microcopy with a bit of British humour. The primary question card should dominate mobile screens. Make layout mobile-first for 320px through desktop; bold, visually balanced, touch-friendly, clear labels, keyboard/focus accessibility and reduced-motion support. Do not use clip art, borrowed trademarks or bovine icons.

## Questions

Include at least 120 original subjective questions divided into: Everyday, Food, People, Hypotheticals, Culture, Debate. Examples: "What's the worst pizza topping?", "What's the biggest red flag on a first date?", "Which animal would be rudest if it could talk?", "What's something people pretend to understand?". Randomise without repeats until the bank is exhausted. Questions should be answerable in 5–15 seconds and create disagreements.

## Privacy and hosting

Provide `<meta name="robots" content="noindex,nofollow,noarchive">` and do not link to the game from the public site navigation. Make room IDs hard to guess and prevent database room listing. Explicitly state **anyone with the full invite link can join**, so this is "secret link" access, not authentication of invited people. Explain Firebase traffic costs, quotas and retention. Document exact install path at `/same-brain/` and expected hosted URL. Include test instructions for host laptop + second phone. Provide all actual, complete source files with no pseudocode and no TODOs except the unavoidable Firebase config values.

## Acceptance tests

- Host creates a room and copies URL.
- Guest joins via the URL with nickname only; host sees player immediately.
- Three guests join and everyone sees the same question.
- Guests enter answers but cannot see each other's answer text until reveal.
- Host merges synonymous answers and reveals the round.
- Everyone sees identical scores, highlighted popular answer and outlier.
- New round starts without refresh, player names and scores remain.
- Fresh browser with no room token cannot list/guess existing rooms.
- Only host can trigger start/reveal/next/finish.
- The same package works when uploaded to static hosting under the provided path.

Return the complete project, a zipped folder, and a beginner-friendly setup guide. Do not present the app as live until Firebase has actually been configured and tested.
