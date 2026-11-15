# SAME BRAIN — ready-to-host multiplayer party game

A bespoke, mobile-first party game created for UKComedyMap.co.uk.

**Important:** This is a *real multiplayer frontend*, not an HTML-only simulation. You must connect a Firebase project before multiple phones can use it. The supplied `index.html`, `styles.css`, `questions.js`, `app.js` and `config.js` can be placed on any static web host; no Node.js hosting is required. The multiplayer state lives in **Firebase Authentication + Cloud Firestore**.

## Files

- `index.html` — single-page entry point with `noindex` metadata
- `styles.css` — mobile-first design
- `app.js` — room creation, joining, scoring, realtime subscriptions, revealing, and sharing
- `questions.js` — 120 original questions; edit or add more here
- `config.js` — where to paste your Firebase public web configuration
- `firestore.rules` — access-control rules for private rooms and players
- `BUILD_PROMPT.md` — standalone AI developer prompt for rebuilding or extending the game

## 1. Set up Firebase

1. Go to https://console.firebase.google.com/ and create a project (or choose an existing one).
2. Add a **Web app** under Project settings → Your apps. Copy the provided `firebaseConfig` object. You don't have to enable Firebase Hosting; UKComedyMap can host these static files.
3. Under **Build → Authentication → Sign-in method**, enable **Anonymous** sign-in. No player accounts or passwords are needed.
4. Under **Build → Firestore Database**, create a database. Select a region near players (for example a European region) and begin with production/security rules — NOT a permanent `allow read, write: if true` policy.
5. Open Firestore → **Rules**, paste all of `firestore.rules`, and click Publish. For a production website, validate access using Firebase Rules Simulator or the local emulator.
6. Replace the placeholders in `config.js` with **your actual Web app Firebase config**. This public configuration is okay to include in a client app. **Never** paste a service account key, private key or admin SDK credentials.
7. Optional: in Firebase Authentication → Settings → Authorized domains, add `www.ukcomedymap.co.uk` if necessary for your project's auth configuration.

Reference: https://firebase.google.com/docs/web/setup and https://firebase.google.com/docs/firestore/security/get-started

## 2. Upload to your website

Place these five public files into a new directory on your site:

```
public_html/
└── same-brain/
    ├── index.html
    ├── styles.css
    ├── app.js
    ├── config.js
    └── questions.js
```

`firestore.rules`, `README.md`, and `BUILD_PROMPT.md` are NOT needed on the live server.

Your start page will be:

**https://www.ukcomedymap.co.uk/same-brain/**

The host types a nickname and clicks **Create a private game**. That generates a hard-to-guess URL like:

`https://www.ukcomedymap.co.uk/same-brain/?room=5a7c...`.

Share the entire URL with guests. They just open it, type a nickname, and join. No accounts, app installs or separate join codes. The host controls the game from their device.

If your web host serves static files from somewhere other than `public_html/`, use its equivalent static website directory. Ensure HTTPS and that JS modules are served with the correct JavaScript content type.

## 3. Test before sharing widely

1. Open the base game URL on your laptop and create a room.
2. Copy the complete invite link to a different phone, or open it in an incognito browser.
3. Join with a second nickname and check that both players are visible.
4. Click **Start game** on the host's device. Both should see the same question.
5. Submit a different answer on each device and check the answer count.
6. On host, open **Review answers**; you should see submitted answers. If equivalent phrases were entered, use **Count this as** to merge them.
7. Click **Reveal results**. All devices should show the same results and updated scores.
8. Click **Next question**, then **Finish game** when done.

Important: Two ordinary tabs in the *same browser profile* normally use the same anonymous Firebase identity. Test with a second device, different browser, or incognito window.

## How the rules work

- Each person types the answer they think **most other people will give**.
- The most popular answer gets one point for each person who gave it. If multiple answers tie for most popular, both groups earn points, provided at least two people chose each answer.
- When **exactly one** answer has been given by just one person (at least three answers submitted), that player receives the **Odd One** badge. The badge passes to the next unique outlier in a later round.
- Reach **8 points** while **not holding the badge** to be eligible to win. The host can finish the game whenever they're ready. If ending early, the highest-scoring eligible player wins.
- All unique answers = no points.
- Answers are matched case-insensitively with basic punctuation trimming; host can merge equivalent phrasings manually before reveal.

This is an original, Herd Mentality-style game with its own name, visuals and prompts, not an official version of that commercial board game.

## Privacy and capacity

- **Link-only** means rooms have long random identifiers and are not publicly indexed or listed by the backend. **Anyone who receives the link can join**. This is privacy by secret URL, not end-to-end encryption or access restricted to invited identities. Avoid sharing private or sensitive information in answers.
- All devices communicate directly with Firebase using anonymous sign-in. Firestore rules stop ordinary participants from changing the room state, seeing unrevealed answers of others, or changing other players' data. The host can view answers for judging.
- The website has **no intentionally coded player cap**; this is not a promise of literally unlimited simultaneous users. Actual traffic, 1 MB per-document limits, Firestore/Authentication quotas, Firebase pricing, client performance, and network connectivity impose practical limits. A very large public event would need load testing and potentially a dedicated backend.
- Rooms and answers persist in Firestore until you remove them. For long-term use, configure a retention/cleanup process; do not assume rooms auto-delete.
- Add your own privacy policy/cookie assessment before deploying for public use, especially if you expect children to play.

## Troubleshooting

- **"One tiny setup step" page:** `config.js` still contains placeholders; fill in the Firebase config.
- **"Operation not allowed":** enable Firebase Anonymous Authentication.
- **"Missing or insufficient permissions":** publish `firestore.rules` and verify the room is valid.
- **Two players look identical:** test with a separate browser/private tab to get different anonymous identities.
- **Can't copy invite link:** host the site over HTTPS (clipboard permissions often need a secure origin).
- **Question doesn't update:** make sure the browser is online and Firestore reads/writes are permitted in the rules.

## Customise

Change colors/typography in `styles.css`, and edit `QUESTIONS` in `questions.js`. Most visible copy and rule labels live in `app.js`. You can adjust the winning threshold by replacing 8 in `app.js` and `README.md`.

The base URL does not show a list of rooms. Don't link it from your website navigation if you want to keep the game unlisted; the `noindex` tag also asks search engines not to index it, but is not a security control.
