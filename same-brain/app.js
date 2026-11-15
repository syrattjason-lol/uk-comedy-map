import { firebaseConfig } from './config.js?v=2';
import { QUESTIONS } from './questions.js?v=2';

const appEl = document.getElementById('app');
const toastEl = document.getElementById('toast');
const nameKey = 'samebrain-name';
const params = new URLSearchParams(location.search);
const roomId = params.get('room') || '';
const inviteLink = roomId ? `${location.origin}${location.pathname}?room=${encodeURIComponent(roomId)}` : '';
const configured = Boolean(firebaseConfig.apiKey && !firebaseConfig.apiKey.includes('PASTE_') && firebaseConfig.projectId && !firebaseConfig.projectId.includes('PASTE_'));

let fb = null, db = null, auth = null, uid = '', room = null, players = [], rounds = [], mySubmission = null;
let joined = false, pageError = '', actionBusy = false, reviewOpen = false, mergeOverrides = {}, answerDraft = '';
let roomUnsub = null, playersUnsub = null, roundsUnsub = null, submissionUnsub = null, currentRoundForSub = '';
let toastTimer;
const $ = (id) => document.getElementById(id);
const esc = (v = '') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const playerName = (id) => players.find(p => p.uid === id)?.name || 'Someone';
const me = () => players.find(p => p.uid === uid);
const amHost = () => room?.hostUid === uid;
const initial = (name) => (String(name || '?').trim().slice(0, 1) || '?').toUpperCase();
const roomRef = () => fb.doc(db, 'rooms', roomId);
const playersRef = () => fb.collection(db, 'rooms', roomId, 'players');
const roundsRef = () => fb.collection(db, 'rooms', roomId, 'rounds');
const submissionRef = (key, id) => fb.doc(db, 'rooms', roomId, 'rounds', String(key), 'submissions', id);
const toast = (message) => { toastEl.textContent = message; toastEl.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => toastEl.classList.remove('show'), 2900); };
const normalize = (value) => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim().replace(/^(the|a|an)\s+/,'').replace(/&/g,'and').replace(/[^a-z0-9\s]/g,'').replace(/\s+/g,' ');
const showError = (error) => { console.error(error); pageError = friendlyError(error); toast(pageError); render(); };
function friendlyError(err) {
  const msg = err?.message || String(err);
  if (/permission-denied|Missing or insufficient permissions/i.test(msg)) return 'Access denied. Check that your Firestore rules are published and Anonymous sign-in is enabled.';
  if (/auth\/operation-not-allowed/i.test(msg)) return 'Enable Anonymous sign-in in Firebase Authentication first.';
  if (/unavailable|network/i.test(msg)) return 'Connection lost. Check your internet connection and try again.';
  return msg.replace(/^Firebase:\s*/,'').slice(0,180);
}
function newQuestion(history = []) {
  const eligible = QUESTIONS.filter(q => !history.includes(q.id));
  const list = eligible.length ? eligible : QUESTIONS;
  const q = list[Math.floor(Math.random() * list.length)];
  return {q, history: eligible.length ? [...history, q.id] : [q.id]};
}
function getScores() {
  const tally = new Map(players.map(p => [p.uid, 0]));
  for (const r of rounds) for (const id of r.winners || []) tally.set(id, (tally.get(id) || 0) + 1);
  const mostRecentOdd = [...rounds].sort((a,b)=>Number(b.roundKey)-Number(a.roundKey)).find(r => r.oddOneUid)?.oddOneUid || '';
  return { tally, oddId: mostRecentOdd, order: [...players].sort((a,b)=>(tally.get(b.uid)||0)-(tally.get(a.uid)||0)||a.name.localeCompare(b.name)) };
}
function getRoundResult() { return rounds.find(r => r.roundKey === room?.roundKey); }
function saveFocusRender() {
  const active = document.activeElement;
  const id = active?.id;
  const pos = active && /^(INPUT|TEXTAREA)$/.test(active.tagName) ? active.selectionStart : null;
  render();
  const next = id && $(id);
  if (next && pos !== null) {
    next.focus({preventScroll:true});
    try { next.setSelectionRange(Math.min(pos,next.value.length),Math.min(pos,next.value.length)); } catch {}
  }
}
function confetti() {
  const colors = ['#d5ff8b','#ff8eaa','#baabff','#fff7ce'];
  for (let i=0;i<75;i++) {
    const el = document.createElement('i');
    el.className='confetti';
    el.style.left=`${Math.random()*100}vw`;
    el.style.background=colors[Math.floor(Math.random()*colors.length)];
    el.style.animationDelay=`${Math.random()*.6}s`;
    el.style.animationDuration=`${1.5+Math.random()*2}s`;
    el.style.transform=`rotate(${Math.random()*180}deg)`;
    document.body.appendChild(el);
    setTimeout(()=>el.remove(),3500);
  }
}
function busy(action) { if (actionBusy) return false; actionBusy=true; render(); return true; }
function done() { actionBusy=false; render(); }

async function start() {
  if (!configured) { render(); return; }
  try {
    const [appMod, authMod, storeMod] = await Promise.all([
      import('https://www.gstatic.com/firebasejs/13.1.0/firebase-app.js'),
      import('https://www.gstatic.com/firebasejs/13.1.0/firebase-auth.js'),
      import('https://www.gstatic.com/firebasejs/13.1.0/firebase-firestore.js')
    ]);
    fb = {...appMod, ...authMod, ...storeMod};
    const instance = fb.initializeApp(firebaseConfig);
    db = fb.getFirestore(instance);
    auth = fb.getAuth(instance);
    const credential = await fb.signInAnonymously(auth);
    uid = credential.user.uid;
    if (roomId) {
      const existing = await fb.getDoc(roomRef());
      if (!existing.exists()) pageError='That room does not exist. Ask the host for a fresh invitation link.';
      else {
        room=existing.data();
        const membership = await fb.getDoc(fb.doc(playersRef(),uid));
        joined=membership.exists();
        subscribeRoom();
        if(joined) subscribeJoined();
      }
    }
    render();
  } catch (e) { showError(e); }
}
function subscribeRoom() {
  roomUnsub?.();
  roomUnsub=fb.onSnapshot(roomRef(),snap=>{
    if(!snap.exists()) {room=null;pageError='This room has closed or cannot be found.';render();return;}
    const oldKey=room?.roundKey;const oldPhase=room?.phase;
    room=snap.data();
    if(oldKey!==room.roundKey){reviewOpen=false;mergeOverrides={};answerDraft='';mySubmission=null;}
    // Every connected phone is notified as soon as the host publishes results.
    if(joined && oldPhase!=='results' && room.phase==='results') {
      confetti();
      if(oldPhase==='answering') {
        toast('The herd has spoken! Results are in.');
        if(typeof navigator.vibrate === 'function') navigator.vibrate([65, 45, 90]);
        window.scrollTo({top:0,behavior:'smooth'});
      }
    }
    if(joined && oldKey!==room.roundKey) subscribeMyAnswer();
    saveFocusRender();
  },showError);
}
function subscribeJoined() {
  playersUnsub?.();roundsUnsub?.();
  playersUnsub=fb.onSnapshot(playersRef(),snap=>{players=snap.docs.map(d=>d.data());saveFocusRender();},showError);
  roundsUnsub=fb.onSnapshot(roundsRef(),snap=>{rounds=snap.docs.map(d=>d.data()).sort((a,b)=>Number(a.roundKey)-Number(b.roundKey));saveFocusRender();},showError);
  subscribeMyAnswer();
}
function subscribeMyAnswer() {
  if(!joined||!room?.roundKey||room.roundKey===currentRoundForSub) return;
  submissionUnsub?.();mySubmission=null;currentRoundForSub=room.roundKey;
  submissionUnsub=fb.onSnapshot(submissionRef(room.roundKey,uid),snap=>{
    mySubmission=snap.exists()?snap.data():null;
    if(mySubmission && !answerDraft) answerDraft=mySubmission.text;
    saveFocusRender();
  },showError);
}
function home() { history.replaceState({},'',location.pathname);window.location.href=location.pathname; }
async function makeRoom(name) {
  if(!busy()) return;
  try {
    localStorage.setItem(nameKey,name);
    const id=crypto.randomUUID();
    const ref=fb.doc(db,'rooms',id);
    await fb.setDoc(ref,{
      hostUid:uid,phase:'lobby',round:0,roundKey:'0',question:'',questionId:-1,history:[],createdAt:fb.serverTimestamp()
    });
    await fb.setDoc(fb.doc(db,'rooms',id,'players',uid),{
      uid,name,answeredRound:0,joinedAt:fb.serverTimestamp()
    });
    location.href=`${location.pathname}?room=${encodeURIComponent(id)}`;
  } catch(e) { showError(e);done(); }
}
async function join(name) {
  if(!busy()) return;
  try {
    localStorage.setItem(nameKey,name);
    await fb.setDoc(fb.doc(playersRef(),uid),{uid,name,answeredRound:0,joinedAt:fb.serverTimestamp()});
    joined=true;subscribeJoined();toast('You’re in! Welcome to the crowd.');done();
  } catch(e) {showError(e);done();}
}
async function beginRound() {
  if(!amHost()||!busy())return;
  try {
    const next=newQuestion(room.history||[]);
    await fb.updateDoc(roomRef(),{
      phase:'answering',round:room.round+1,roundKey:String(room.round+1),question:next.q.text,
      questionId:next.q.id,category:next.q.category,history:next.history
    });
    reviewOpen=false;mergeOverrides={};toast('New question is live!');done();
  } catch(e){showError(e);done();}
}
async function submitAnswer() {
  const text=answerDraft.trim().replace(/\s+/g,' ');
  if(!text) {toast('Write an answer first.');return;}
  if(text.length>80) {toast('Keep it under 80 characters.');return;}
  if(!joined||room?.phase!=='answering'||!busy())return;
  try {
    const batch=fb.writeBatch(db);
    batch.set(submissionRef(room.roundKey,uid),{uid,text,submittedAt:fb.serverTimestamp()});
    batch.update(fb.doc(playersRef(),uid),{answeredRound:room.round});
    await batch.commit();
    toast('Answer locked in. Great minds, etc.');done();
  }catch(e){showError(e);done();}
}
function baseGroups(subs) {
  const map=new Map();
  for(const sub of subs){
    const key=normalize(sub.text);
    if(!key)continue;
    if(!map.has(key))map.set(key,{key,label:sub.text,members:[],answers:[]});
    map.get(key).members.push(sub.uid);map.get(key).answers.push(sub.text);
  }
  return [...map.values()].sort((a,b)=>b.members.length-a.members.length||a.label.localeCompare(b.label));
}
function resolveKey(key) {
  const seen=new Set();
  while(mergeOverrides[key]&&!seen.has(key)){seen.add(key);key=mergeOverrides[key];}
  return key;
}
function mergedGroups(groups) {
  const map=new Map();
  for(const g of groups){
    const target=resolveKey(g.key);
    if(!map.has(target)){
      const candidate=groups.find(x=>x.key===target)||g;
      map.set(target,{label:candidate.label,members:[],answers:[]});
    }
    const item=map.get(target);item.members.push(...g.members);item.answers.push(...g.answers);
  }
  return [...map.values()].sort((a,b)=>b.members.length-a.members.length||a.label.localeCompare(b.label));
}
async function reveal() {
  if(!amHost()||room.phase!=='answering'||!busy())return;
  try {
    const subs=await fb.getDocs(fb.collection(db,'rooms',roomId,'rounds',room.roundKey,'submissions'));
    const answers=subs.docs.map(d=>d.data());
    const groups=mergedGroups(baseGroups(answers));
    const highest=groups.reduce((max,g)=>Math.max(max,g.members.length),0);
    const winners=highest>=2?groups.filter(g=>g.members.length===highest).flatMap(g=>g.members):[];
    const loners=groups.filter(g=>g.members.length===1);
    const oddOneUid=(answers.length>=3 && loners.length===1)?loners[0].members[0]:'';
    const batch=fb.writeBatch(db);
    batch.set(fb.doc(roundsRef(),room.roundKey),{
      roundKey:room.roundKey,question:room.question,category:room.category||'Surprise',
      groups:groups.map(g=>({label:g.label,count:g.members.length,members:g.members})),
      winners,oddOneUid,answered:answers.length,createdAt:fb.serverTimestamp()
    });
    batch.update(roomRef(),{phase:'results'});
    await batch.commit();reviewOpen=false;toast('Results are in!');done();
  } catch(e) {showError(e);done();}
}
async function finish() {
  if(!amHost()||!busy())return;
  try{await fb.updateDoc(roomRef(),{phase:'finished'});confetti();done();}
  catch(e){showError(e);done();}
}
async function copyLink() {
  try{await navigator.clipboard.writeText(inviteLink);toast('Private invite link copied!');}
  catch(e){const input=document.createElement('textarea');input.value=inviteLink;document.body.appendChild(input);input.select();document.execCommand('copy');input.remove();toast('Link copied.');}
}
async function shareLink() {
  if(navigator.share){try{await navigator.share({title:'Same Brain party',text:'Join our Same Brain game!',url:inviteLink});}catch(e){if(e.name!=='AbortError')copyLink();}}
  else copyLink();
}
function currentScores(){return getScores();}
function playerRow(p,index,scores){
  const score=scores.tally.get(p.uid)||0;
  const hasAnswered=room.phase==='answering'&&p.answeredRound===room.round;
  return `<div class="player"><div class="player-left"><span class="avatar-bubble">${esc(initial(p.name))}</span><span class="player-name" title="${esc(p.name)}">${esc(p.name)}${p.uid===uid?' <span class="muted">(you)</span>':''}${scores.oddId===p.uid?' <span class="label-odd">ODD ONE</span>':''}</span></div><span class="${hasAnswered?'ready':''} tiny">${hasAnswered?'✓ ':''}${score} pt${score===1?'':'s'}</span></div>`;
}
function sidebar() {
  const scores=currentScores();
  const answered=players.filter(p=>p.answeredRound===room.round).length;
  return `<aside class="side">
    <div class="side-card"><h2 class="side-title">The crowd <span class="chip">${players.length} playing</span></h2>
      ${room.phase==='answering'?`<div class="progress-row"><span>Answers in</span><strong>${answered} / ${players.length}</strong></div><div class="progress-track"><div class="progress-bar" style="width:${players.length?Math.min(100,100*answered/players.length):0}%"></div></div>`:''}
      <div class="players-list">${scores.order.map((p,i)=>playerRow(p,i,scores)).join('')||'<p class="empty">Waiting for your people…</p>'}</div>
    </div>
    <div class="side-card"><h2 class="side-title">How to win <span>✳</span></h2>
      <div class="new-rule"><i>🧠</i><span>Think of the answer <strong>everyone else</strong> will give.</span></div>
      <div class="new-rule"><i>✨</i><span>Most popular answer gets <strong>1 point</strong>.</span></div>
      <div class="new-rule"><i>🦆</i><span>One lone answer earns the <strong>Odd One</strong> badge.</span></div>
      <div class="new-rule"><i>🏆</i><span>Get <strong>8 points</strong> without the badge to win.</span></div>
      <p class="micro" style="margin:14px 0 0">Tied top answers score. If everyone answers differently, nobody scores.</p>
    </div>
  </aside>`;
}
function ribbon(){return `<div class="top-ribbon"><div><div class="room-label">Private room · Share this link with friends</div><div class="room-code">ROOM ${esc(roomId.slice(-6).toUpperCase())}</div></div><div class="room-actions"><button class="btn btn-quiet small-btn" data-action="copy">⧉ Copy invite</button><button class="btn btn-secondary small-btn" data-action="share">↗ Share</button></div></div>`;}
function frame(content){return `${ribbon()}<div class="game-grid"><section class="stage">${content}</section>${sidebar()}</div>`;}
function isDisabled(){return actionBusy?'disabled':'';}
function lobbyScreen(){return frame(`<div class="stage-ribbon"><span class="chip hot">● LOBBY OPEN</span><span class="chip">${amHost()?'YOU’RE THE HOST':'WAITING FOR HOST'}</span></div><h1>Get the gang together.</h1><p class="stage-intro">Everyone needs their own phone. Send the invite link; they open it, pick a nickname, and they're in.</p><div class="outline-box"><p class="section-label">Your private invite</p><div class="invite-url">${esc(inviteLink)}</div><div class="button-row"><button class="btn btn-primary" data-action="copy">⧉ Copy invite link</button><button class="btn btn-secondary" data-action="share">↗ Share</button></div></div><div class="divider"></div><p class="section-label">Already here · ${players.length} player${players.length===1?'':'s'}</p><div class="avatars">${players.map(p=>`<span class="avatar"><span class="avatar-bubble">${esc(initial(p.name))}</span>${esc(p.name)}${p.uid===room.hostUid?' 👑':''}</span>`).join('')}</div><div class="button-row" style="margin-top:29px">${amHost()?`<button class="btn btn-pink" data-action="next" ${isDisabled()}>Start game →</button><span class="tiny muted">You can start with any group size.</span>`:'<div class="feedback">You’re in! The host will start when everyone is ready.</div>'}</div>`);}
function answeringScreen() {
  const count=players.filter(p=>p.answeredRound===room.round).length;
  const mine=!!mySubmission;
  return frame(`<div class="question-nav"><div class="stage-ribbon"><span class="chip hot">ROUND ${room.round}</span><span class="chip">${esc(room.category||'Surprise')}</span></div><span class="tiny muted">${count} of ${players.length} answered</span></div>
    <div class="question-card"><div class="tiny-label">THE BIG QUESTION</div><h2>${esc(room.question)}</h2></div>
    ${mine?`<div class="feedback">✓ You've answered: <strong>${esc(mySubmission.text)}</strong></div><p class="helper">You can change your answer until the host reveals the results.</p>`:`<p class="stage-intro">Don't be original. Guess what the room will say.</p>`}
    <form id="answer-form" class="answer-area"><label class="form-label" for="answer-input">Your answer</label><input class="text-input" id="answer-input" maxlength="80" placeholder="What will everyone else write?" autocomplete="off" value="${esc(answerDraft)}" required><div class="button-row"><button class="btn btn-primary" type="submit" ${isDisabled()}>${mine?'Update answer ↗':'Lock in answer →'}</button><span class="tiny muted">Only your answer is visible to you until reveal.</span></div></form>
    ${amHost()?`<div class="divider"></div><p class="section-label">Host controls</p><div class="button-row"><button class="btn btn-secondary" data-action="review" ${isDisabled()}>${reviewOpen?'Hide answer review':'Review answers'} (${count})</button><button class="btn btn-pink" data-action="reveal" ${isDisabled()}>Reveal results ✦</button></div><p class="helper">Review and merge equivalent answers before you reveal them to the group.</p>${reviewOpen?`<div id="review-area" class="answer-groups"><p class="tiny muted">Fetching the latest answers…</p></div>`:''}`:''}`);
}
function resultsScreen() {
  const res=getRoundResult();
  if(!res)return frame(`<div class="loader"></div><h1>The votes are being counted…</h1><p class="stage-intro">Results will appear here automatically on every phone.</p>`);
  const groups=res.groups||[];
  const max=Math.max(0,...groups.map(g=>g.count));
  const scored=(res.winners||[]).length>0;
  const winners=scored?groups.filter(g=>g.count===max):[];
  const oddGroup=res.oddOneUid ? groups.find(g=>g.members.includes(res.oddOneUid)) : null;
  const mine=groups.find(g=>g.members.includes(uid));
  const earnedPoint=(res.winners||[]).includes(uid);
  const iAmOdd=res.oddOneUid===uid;
  const scores=currentScores();
  const myScore=scores.tally.get(uid)||0;
  const contenders=scores.order.filter(p=>(scores.tally.get(p.uid)||0)>=8 && scores.oddId!==p.uid);

  let verdictTitle,verdictSub,verdictClass,verdictIcon;
  if(!mine) {
    verdictTitle='You sat this one out';verdictSub='No answer submitted this round.';verdictClass='quiet';verdictIcon='👀';
  } else if(iAmOdd) {
    verdictTitle='YOU’RE THE ODD ONE!';verdictSub=`Only you answered “${mine.label}”. You have the Odd One badge.`;verdictClass='odd';verdictIcon='🐮';
  } else if(earnedPoint) {
    verdictTitle='+1 POINT!';verdictSub='You matched the most popular answer. Same brain!';verdictClass='won';verdictIcon='🎉';
  } else if(!scored) {
    verdictTitle='TOTAL CHAOS';verdictSub='No answers matched, so nobody scored.';verdictClass='quiet';verdictIcon='🤯';
  } else {
    verdictTitle='Not quite the same brain';verdictSub=`You answered “${mine.label}”. No point this time.`;verdictClass='quiet';verdictIcon='🫠';
  }

  const winningContents=scored
    ? winners.map(g=>`<div class="spotlight-entry"><strong class="spotlight-answer">${esc(g.label)}</strong><span class="spotlight-votes">${g.count} vote${g.count===1?'':'s'}</span><div class="spotlight-people">${g.members.map(id=>esc(playerName(id))).join(' · ')}</div></div>`).join('')
    : `<div class="spotlight-answer no-match">No matching answers</div><div class="spotlight-people">Nobody earned a point this round.</div>`;
  const oddContents=oddGroup
    ? `<strong class="spotlight-answer">${esc(oddGroup.label)}</strong><span class="spotlight-votes">1 vote</span><div class="spotlight-people"><strong>${esc(playerName(res.oddOneUid))}</strong> thought differently</div>`
    : `<strong class="spotlight-answer no-match">No single odd one</strong><div class="spotlight-people">No new Odd One badge this round.${scores.oddId?` <strong>${esc(playerName(scores.oddId))}</strong> still holds it.`:''}</div>`;
  return frame(`
    <div class="stage-ribbon"><span class="chip hot">✦ LIVE REVEAL · ROUND ${room.round}</span><span class="chip pink">${res.answered} answers in</span></div>
    <div class="reveal-intro"><h1 class="reveal-title">The herd has spoken<span class="reveal-spark">✳</span></h1><p class="reveal-question">${esc(res.question)}</p></div>
    <section class="personal-verdict ${verdictClass}" role="status" aria-live="polite" aria-label="Your personal round result">
      <span class="verdict-emoji" aria-hidden="true">${verdictIcon}</span>
      <div class="verdict-copy"><span class="verdict-kicker">YOUR RESULT</span><strong>${verdictTitle}</strong><p>${esc(verdictSub)}</p></div>
      <div class="verdict-score"><strong>${myScore}</strong><span>YOUR TOTAL</span></div>
    </section>
    <div class="reveal-spotlights" aria-label="Winning and odd-one-out answers">
      <section class="spotlight-card spotlight-winning">
        <div class="spotlight-kicker">🏆 ${winners.length>1?'WINNING ANSWERS':'WINNING ANSWER'}</div>
        ${winningContents}
      </section>
      <section class="spotlight-card spotlight-odd">
        <div class="spotlight-kicker">🐮 ODD ONE OUT</div>
        ${oddContents}
      </section>
    </div>
    <details class="results-breakdown"><summary>See every answer <span>${groups.length} different answer${groups.length===1?'':'s'}</span></summary>
      <div class="result-list">${groups.map(g=>`<div class="answer-group ${scored&&g.count===max?'winner':''}"><div class="answer-head"><span class="answer-name">${scored&&g.count===max?'🏆 ':''}${esc(g.label)}</span><span class="answer-count">${g.count} ${g.count===1?'vote':'votes'}</span></div><div class="answer-members">${g.members.map(id=>esc(playerName(id))).join(' · ')}</div></div>`).join('')||'<p class="empty">Nobody submitted an answer.</p>'}</div>
    </details>
    ${amHost()?`<div class="button-row reveal-controls">${contenders.length?`<button class="btn btn-primary" data-action="finish" ${isDisabled()}>Crown the winner 🏆</button><button class="btn btn-secondary" data-action="next" ${isDisabled()}>Keep playing →</button>`:`<button class="btn btn-primary" data-action="next" ${isDisabled()}>Next question →</button><button class="btn btn-secondary" data-action="finish" ${isDisabled()}>Finish game</button>`}</div><p class="helper">Everyone can see their own result and the winning answers. Give the group a moment to react before continuing.</p>`:'<div class="results-waiting" role="status">✳ Waiting for the host to start the next round…</div>'}
  `);
}
function finishedScreen() {
  const scores=currentScores();
  const eligible=scores.order.filter(p=>p.uid!==scores.oddId);
  const winner=eligible[0]||scores.order[0];
  const high=winner?(scores.tally.get(winner.uid)||0):0;
  const winners=eligible.filter(p=>(scores.tally.get(p.uid)||0)===high);
  return frame(`<div class="stage-ribbon"><span class="chip pink">GAME OVER</span><span class="chip hot">${rounds.length} rounds played</span></div><div class="starfield">✳ ✷ ✦ ✳</div><h1>The crowd has spoken.</h1><div class="winner-panel"><div class="tiny-label">${winners.length===1?'TOP BRAIN':'TOP BRAINS'}</div><div class="winner-big">${winners.map(p=>esc(p.name)).join(' & ')||'Everyone'}</div><p class="muted" style="margin-bottom:0">${high} point${high===1?'':'s'} · ${winners.length===1?'Crowned the crowd favourite':'Shared the top spot'}</p></div><p class="stage-intro">Same brain. Same wavelength. Questionable judgement.</p><div class="button-row"><button class="btn btn-primary" data-action="home">Start a new game →</button><button class="btn btn-secondary" data-action="copy">Copy this room's link</button></div>`);
}
function setupScreen(){
  return `<div class="welcome-layout"><div><div class="eyebrow">A PARTY GAME FOR PEOPLE WITH FRIENDS</div><h1 class="hero-title">One room.<br><em>Same brain.</em></h1><p class="hero-copy">Try to give the same answer as everyone else. Be too original and you might just lose. Play on your own phones, together in real time.</p><div class="feature-row"><span class="feature-pill">✳ No downloads</span><span class="feature-pill">✳ No player cap</span><span class="feature-pill">✳ Invite link only</span></div><div class="hero-art"><div class="hero-face">😎</div><div class="hero-face">🧠</div><div class="hero-face">🤔</div><div class="hero-face">🥳</div></div></div><div class="panel"><h2 class="panel-title">One tiny setup step.</h2><p class="panel-desc">The website files are ready. To make live multiplayer work, add your free Firebase project settings to <code>config.js</code>.</p><div class="outline-box"><p class="form-label">Setup checklist</p><div class="new-rule"><i>1.</i> <span>Create a Firebase web project.</span></div><div class="new-rule"><i>2.</i> <span>Turn on <strong>Anonymous Authentication</strong>.</span></div><div class="new-rule"><i>3.</i> <span>Create a <strong>Firestore Database</strong>.</span></div><div class="new-rule"><i>4.</i> <span>Publish the supplied <strong>firestore.rules</strong>.</span></div><div class="new-rule"><i>5.</i> <span>Paste the web app configuration into <strong>config.js</strong>.</span></div></div><p class="form-note">See README.md for precise instructions.</p></div></div>`;
}
function welcomeScreen(){return `<div class="welcome-layout"><div><div class="eyebrow">YOUR FRIENDS. ONE COLLECTIVE BRAIN CELL.</div><h1 class="hero-title">One room.<br><em>Same brain.</em></h1><p class="hero-copy">The party game where the smartest answer is the one everyone else gives. Think alike, score points, and try not to be the odd one out.</p><div class="feature-row"><span class="feature-pill">✳ Unlimited invites*</span><span class="feature-pill">✳ No sign-ups</span><span class="feature-pill">✳ Live on every phone</span></div><div class="hero-art"><div class="hero-face">😎</div><div class="hero-face">🧠</div><div class="hero-face">🤔</div><div class="hero-face">🥳</div></div><p class="micro" style="margin-top:17px">* No artificial player cap; service capacity and quotas still apply.</p></div><div class="panel"><h2 class="panel-title">Bring your people.</h2><p class="panel-desc">Host a game. Copy the private link. Everyone joins from their phone in seconds.</p><form id="create-form" class="form-stack"><div><label class="form-label" for="create-name">What should we call you?</label><input id="create-name" class="text-input" maxlength="24" required placeholder="Your nickname" autocomplete="nickname" value="${esc(localStorage.getItem(nameKey)||'')}"></div><button class="btn btn-primary btn-full" type="submit" ${isDisabled()}>Create a private game →</button></form><div class="separator"><span>GOT AN INVITE?</span></div><p class="form-note">Just open your friend's link. No code, account, or app required.</p><div class="stat-strip"><div><strong>120</strong>questions</div><div><strong>8</strong>points to win</div><div><strong>0</strong>awkward setup</div></div></div></div>`;}
function joinScreen(){return `<div class="welcome-layout"><div><div class="eyebrow">YOU'VE BEEN INVITED</div><h1 class="hero-title">Join the<br><em>hive mind.</em></h1><p class="hero-copy">Your friends are waiting. Pick a nickname, write down answers, and see if you're all on the same wavelength.</p><div class="hero-art"><div class="hero-face">🥳</div><div class="hero-face">🧠</div><div class="hero-face">👀</div></div></div><div class="panel"><span class="chip hot">INVITE LINK VERIFIED</span><h2 class="panel-title" style="margin-top:17px">You're almost in.</h2><p class="panel-desc">No account needed, just your nickname.</p><form id="join-form" class="form-stack"><div><label class="form-label" for="join-name">Nickname</label><input id="join-name" class="text-input" maxlength="24" required placeholder="What should we call you?" autocomplete="nickname" value="${esc(localStorage.getItem(nameKey)||'')}"></div><button type="submit" class="btn btn-primary btn-full" ${isDisabled()}>Join the game →</button></form><p class="form-note">Room ${esc(roomId.slice(-6).toUpperCase())} · Private by link</p></div></div>`;}
function errorScreen(){return `<div class="panel" style="max-width:580px;margin:70px auto;text-align:center"><h1 class="panel-title">Oops. The brains got crossed.</h1><p class="stage-intro">${esc(pageError)}</p><a class="btn btn-primary" href="./">Go to home →</a></div>`;}
function render() {
  if(pageError){appEl.innerHTML=errorScreen();return;}
  if(!configured){appEl.innerHTML=setupScreen();return;}
  if(!uid){appEl.innerHTML='<section class="welcome-shell"><div class="loader"></div><p>Getting the gang together…</p></section>';return;}
  if(!roomId){appEl.innerHTML=welcomeScreen();return;}
  if(!room){appEl.innerHTML='<section class="welcome-shell"><div class="loader"></div><p>Finding your party…</p></section>';return;}
  if(!joined){appEl.innerHTML=joinScreen();return;}
  if(room.phase==='lobby')appEl.innerHTML=lobbyScreen();
  else if(room.phase==='answering')appEl.innerHTML=answeringScreen();
  else if(room.phase==='results')appEl.innerHTML=resultsScreen();
  else if(room.phase==='finished')appEl.innerHTML=finishedScreen();
  else appEl.innerHTML=errorScreen();
  if(room.phase==='answering' && amHost() && reviewOpen) loadReview();
}
async function loadReview(){
  const current=room.roundKey;
  try{
    const snapshot=await fb.getDocs(fb.collection(db,'rooms',roomId,'rounds',current,'submissions'));
    if(!reviewOpen||room.roundKey!==current)return;
    const groups=baseGroups(snapshot.docs.map(d=>d.data()));
    const holder=$('review-area');if(!holder)return;
    if(!groups.length){holder.innerHTML='<p class="empty">Nobody has submitted an answer yet.</p>';return;}
    holder.innerHTML='<p class="section-label">Merge matching ideas before revealing</p>'+
      groups.map(g=>`<div class="answer-group"><div class="answer-head"><strong class="answer-name">${esc(g.label)}</strong><span class="answer-count">${g.members.length} vote${g.members.length===1?'':'s'}</span></div><div class="answer-members">${g.members.map(id=>esc(playerName(id))).join(' · ')}</div><div class="merge-row"><label for="merge-${encodeURIComponent(g.key)}">Count this as:</label><select class="merge-select" data-merge="${esc(g.key)}" id="merge-${encodeURIComponent(g.key)}"><option value="">Keep separate</option>${groups.filter(x=>x.key!==g.key).map(x=>`<option value="${esc(x.key)}" ${mergeOverrides[g.key]===x.key?'selected':''}>${esc(x.label)}</option>`).join('')}</select></div></div>`).join('')+
      '<p class="helper">Example: merge “washing dishes” into “washing up”. Matching punctuation and capitals are grouped automatically.</p>';
  }catch(e){const holder=$('review-area');if(holder)holder.innerHTML=`<p class="notice">${esc(friendlyError(e))}</p>`;}
}
appEl.addEventListener('submit', async ev=>{
  ev.preventDefault();
  if(ev.target.id==='create-form'){const name=$('create-name')?.value.trim().replace(/\s+/g,' ').slice(0,24);if(name)await makeRoom(name);}
  else if(ev.target.id==='join-form'){const name=$('join-name')?.value.trim().replace(/\s+/g,' ').slice(0,24);if(name)await join(name);}
  else if(ev.target.id==='answer-form')await submitAnswer();
});
appEl.addEventListener('input',ev=>{if(ev.target.id==='answer-input')answerDraft=ev.target.value;});
appEl.addEventListener('change',ev=>{if(ev.target.dataset.merge!==undefined){const key=ev.target.dataset.merge; const target=ev.target.value;if(target && resolveKey(target)===key){toast('That would create a circular merge. Choose another answer.');ev.target.value='';delete mergeOverrides[key];return;}if(target)mergeOverrides[key]=target;else delete mergeOverrides[key];}});
appEl.addEventListener('click',async ev=>{
  const button=ev.target.closest('[data-action]');if(!button)return;
  const action=button.dataset.action;
  if(action==='home')home();
  if(action==='copy')await copyLink();
  if(action==='share')await shareLink();
  if(action==='next')await beginRound();
  if(action==='review'){reviewOpen=!reviewOpen;render();}
  if(action==='reveal')await reveal();
  if(action==='finish')await finish();
});
start();
