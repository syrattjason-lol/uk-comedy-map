import { firebaseConfig } from './config.js?v=3';
window.__roomSwapStarted = true;

const ROOT = 'roomSwapRooms';
const app = document.getElementById('app');
const toastEl = document.getElementById('toast');
const params = new URLSearchParams(location.search);
const roomId = params.get('game') || '';
const invite = roomId ? `${location.origin}${location.pathname}?game=${encodeURIComponent(roomId)}` : '';
let f, db, auth, uid = '', room = null, players = [], secret = null;
let joined = false, busy = false, error = '', roleVisible = false, chosen = [], movedTo = '', previousArea = '';
let mySelection = null, selections = {A:null,B:null}, activeSelArea = '';
let unsubRoom, unsubPlayers, unsubSecret, unsubSelectionA, unsubSelectionB;
let toastT, voteApplying = false, ticking = false, autoEnding = false;
let initStage = 'Loading the game libraries…', initSlow = false;
const esc = (s='') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const me = () => players.find(p=>p.uid===uid);
const nameOf = id => players.find(p=>p.uid===id)?.name || 'Someone';
const isHost = () => room?.hostUid === uid;
const myArea = () => me()?.area || '';
const isLeader = area => room?.leaders?.[area] === uid;
const areaLabel = a => a === 'A' ? 'Room A' : 'Room B';
const fmtClock = ms => {const s=Math.max(0,Math.ceil(ms/1000));return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
const duration = round => [180000,120000,60000][Math.max(0,Math.min(2,round-1))];
const hostagesNeeded = (count, round) => count <= 10 ? 1 : count <= 21 ? [2,1,1][round-1] : [3,2,1][round-1];
const rand = () => [...crypto.getRandomValues(new Uint8Array(18))].map(b=>b.toString(16).padStart(2,'0')).join('');
const shuffle = list => {const a=[...list];for(let i=a.length-1;i>0;i--){const j=crypto.getRandomValues(new Uint32Array(1))[0]%(i+1);[a[i],a[j]]=[a[j],a[i]];}return a;};
const refRoom = () => f.doc(db,ROOT,roomId);
const refPlayers = () => f.collection(db,ROOT,roomId,'players');
const refPlayer = id => f.doc(refPlayers(),id);
const refSecret = id => f.doc(db,ROOT,roomId,'secrets',id);
const refSelect = a => f.doc(db,ROOT,roomId,'selections',a);
function toast(msg){toastEl.textContent=msg;toastEl.classList.add('show');clearTimeout(toastT);toastT=setTimeout(()=>toastEl.classList.remove('show'),3300);}
function fail(e){console.error(e);const code=e?.code||'';const msg=e?.message||String(e);error = code==='permission-denied'?'Firestore rules are blocking this action. Check the published Room Swap rules.':code==='auth/operation-not-allowed'||code==='auth/admin-restricted-operation'?'Anonymous sign-in is disabled. Enable it in Firebase Authentication → Sign-in method.':code.startsWith('auth/')?`Firebase sign-in error: ${code}. ${msg.slice(0,140)}`:msg.slice(0,230);toast(error);render();}
async function action(fn){if(busy)return;busy=true;render();try{await fn();error='';}catch(e){fail(e);}finally{busy=false;render();}}
async function init(){
  const slowWatch=setTimeout(()=>{if(!uid&&!error){initSlow=true;render();}},10000);
  try{
    render();
    const [a,b,c]=await Promise.all([import('https://www.gstatic.com/firebasejs/13.1.0/firebase-app.js'),import('https://www.gstatic.com/firebasejs/13.1.0/firebase-auth.js'),import('https://www.gstatic.com/firebasejs/13.1.0/firebase-firestore.js')]);
    f={...a,...b,...c};
    initStage='Signing you in securely…';render();
    const firebase=f.initializeApp(firebaseConfig,'room-swap');auth=f.getAuth(firebase);db=f.getFirestore(firebase);
    const current=await f.signInAnonymously(auth);uid=current.user.uid;
    initSlow=false;
    if(roomId) connect();else render();
  }catch(e){fail(e);}finally{clearTimeout(slowWatch);}
}
function connect(){
  unsubRoom=f.onSnapshot(refRoom(),snap=>{if(!snap.exists()){error='Room not found. Ask for a new link.';room=null;render();return;}
    const prev=room?.phase;room=snap.data();
    if(prev && prev!=='ended' && room.phase==='ended'){try{navigator.vibrate?.([130,70,130]);}catch{}}
    render(); syncSelection();
  },fail);
  unsubPlayers=f.onSnapshot(refPlayers(),snap=>{
    const old=previousArea;players=snap.docs.map(d=>d.data()).sort((a,b)=>a.name.localeCompare(b.name));
    joined=players.some(p=>p.uid===uid);const now=myArea();
    if(joined&&!unsubSecret){unsubSecret=f.onSnapshot(refSecret(uid),s=>{secret=s.exists()?s.data():null;render();},fail);}
    if(old && now && old!==now){movedTo=now;roleVisible=false;chosen=[];try{navigator.vibrate?.([180,90,180,90,300]);}catch{}}
    previousArea=now;render();syncSelection();
    if(isHost())maybeApplyVotes();
  },fail);
}
function syncSelection(){
  if(!room||!joined||room.phase==='lobby')return;
  const area=myArea();
  if(isHost()){
    if(!unsubSelectionA)unsubSelectionA=f.onSnapshot(refSelect('A'),s=>{selections.A=s.exists()?s.data():null;render();},()=>{});
    if(!unsubSelectionB)unsubSelectionB=f.onSnapshot(refSelect('B'),s=>{selections.B=s.exists()?s.data():null;render();},()=>{});
  }else if(area && activeSelArea!==area){
    unsubSelectionA?.();unsubSelectionB?.();unsubSelectionA=unsubSelectionB=null;activeSelArea=area;selections={A:null,B:null};
    const un=f.onSnapshot(refSelect(area),s=>{selections[area]=s.exists()?s.data():null;render();},()=>{});
    if(area==='A')unsubSelectionA=un;else unsubSelectionB=un;
  }
  mySelection=selections[area]||null;
}
async function maybeApplyVotes(){
  if(!room||room.phase!=='talk'||voteApplying||!joined||!isHost())return;
  for(const area of ['A','B']){
    const members=players.filter(p=>p.area===area);
    const totals=new Map();for(const p of members)if(p.vote&&members.some(m=>m.uid===p.vote))totals.set(p.vote,(totals.get(p.vote)||0)+1);
    const majority=[...totals.entries()].find(([target,n])=>n>members.length/2&&room.leaders?.[area]!==target);
    if(majority){voteApplying=true;
      try{const batch=f.writeBatch(db);batch.update(refRoom(),{[`leaders.${area}`]:majority[0]});for(const p of members)batch.update(refPlayer(p.uid),{vote:''});await batch.commit();toast(`${nameOf(majority[0])} is the new ${areaLabel(area)} leader!`);}catch(e){console.warn(e);}finally{voteApplying=false;}break;
    }
  }
}
function nameInput(){return `<div class="field"><label for="nickname">YOUR NICKNAME</label><input class="input" id="nickname" maxlength="24" autocomplete="nickname" value="${esc(localStorage.getItem('room-swap-name')||'')}" placeholder="e.g. Alex"></div>`;}
function welcome(){return `<div class="split"><div><span class="eyebrow">✳ A GAME FOR PEOPLE WITH TRUST ISSUES</span><h1 class="hero">Two rooms.<br><span class="pink">One big</span><br><span class="blue">secret.</span></h1><p class="subhead">An in-person party game of secret teams, bluffing and high-stakes hostage swaps. Your phone handles the rules. You do the lying.</p><div class="tags"><span class="chip">✳ 6–30 players</span><span class="chip">✳ 3 timed rounds</span><span class="chip">✳ Private invite link</span></div></div><div class="card"><p class="micro">HOST A NEW GAME</p><h2>Ready to swap sides?</h2><p class="muted">You'll need two separate spaces where players can't hear the other room.</p>${nameInput()}<button class="btn full" id="create" ${busy?'disabled':''}>Create a private room →</button><div class="divider"></div><div class="steps"><div><span class="stepnum">1</span> Invite everyone with your link</div><div><span class="stepnum">2</span> Secret roles appear on each phone</div><div><span class="stepnum">3</span> Talk, bluff, and swap players</div></div></div></div>`;}
function joinUI(){return `<div class="split"><div><span class="eyebrow">✳ YOU'VE BEEN INVITED</span><h1 class="hero">Come in.<br><span class="pink">Trust no one.</span></h1><p class="subhead">One nickname. One secret role. Two rooms full of people who may be lying to you.</p></div><div class="card"><p class="micro">PRIVATE GAME</p><h2>Join the party</h2>${nameInput()}<button class="btn full" id="join" ${busy||room?.phase!=='lobby'?'disabled':''}>Join game →</button>${room?.phase!=='lobby'?'<p class="muted small">This game has already started. Ask the host to create a new room.</p>':''}</div></div>`;}
function peopleCards(list,withArea=false){return `<div class="people">${list.map(p=>`<div class="person"><span class="avatar">${esc((p.name||'?').slice(0,1).toUpperCase())}</span><div class="person-text"><div class="person-name">${esc(p.name)}${p.uid===uid?' (you)':''}</div><div class="person-sub">${withArea?areaLabel(p.area):p.uid===room?.hostUid?'HOST':'PLAYER'}</div></div></div>`).join('')}</div>`;}
function lobby(){return `<div class="gamewrap"><div class="gamehead"><div><p class="micro">PRIVATE LOBBY</p><h1>Gather your <span class="lime">suspects.</span></h1><p class="muted">${players.length} / 6 minimum · Recommended 6–30 players</p></div><span class="chip">LOBBY OPEN</span></div><div class="twocol"><div class="card"><h2>Invite your people</h2><p class="muted">Send this URL to anyone in the room.</p><input id="invite-link" class="input" readonly value="${esc(invite)}"><div class="actions" style="margin-top:12px"><button class="btn" id="copy">Copy invite link</button><button class="btn secondary" id="share">Share ↗</button></div><div class="divider"></div><p class="muted small">Separate your guests into two real spaces before starting. Keep screens private unless you deliberately show your role.</p></div><div class="card"><h2>Players (${players.length})</h2>${peopleCards(players)}${isHost()?`<div class="divider"></div><button class="btn full" id="start" ${players.length<6||players.length>30||busy?'disabled':''}>Deal secret roles & start →</button><p class="muted small">You're the host and can still play. Best with 6–30 players.</p>`:'<p class="muted small">Waiting for the host to start…</p>'}</div></div></div>`;}
function secretCard(){
  if(!secret)return `<div class="secret-mask"><strong>Preparing your role…</strong><p class="muted small">The host is dealing the roles.</p></div>`;
  if(!roleVisible)return `<div class="secret-mask"><span style="font-size:33px">🔒</span><strong>Your role is hidden</strong><p class="muted small">Only reveal it when nobody's looking — or when you want someone to see it.</p><button class="btn secondary slim" id="show-role">Reveal my card 👁</button></div>`;
  const role=secret.role;
  const team=secret.team;
  const classes=team==='blue'?'blue':team==='red'?'red':'gray';
  const symbol=role==='President'?'🏛️':role==='Bomber'?'💣':role==='Gambler'?'🎲':team==='blue'?'🔵':'🔴';
  const help=role==='President'?'Stay away from the Bomber in the final room.':role==='Bomber'?'End up in the same room as the President.':role==='Gambler'?'Predict the winning team before the final reveal.':team==='red'?'Help the Bomber find the President.':'Keep the President safe.';
  return `<div class="secret ${classes}"><p class="micro">EYES ONLY · SECRET ROLE</p><div class="secret-icon">${symbol}</div><h2>${esc(role)}</h2><p>${team==='neutral'?'NEUTRAL PLAYER':team.toUpperCase()+' TEAM'} · ${help}</p><div style="margin-top:20px"><button class="btn secondary slim" id="hide-role">Hide my role 🔒</button></div>${role==='Gambler'?`<div class="divider"></div><p class="small">Predict the winning side:</p><div class="actions"><button class="btn ${secret.guess==='blue'?'blue':'secondary'} slim" data-guess="blue">Blue</button><button class="btn ${secret.guess==='red'?'red':'secondary'} slim" data-guess="red">Red</button></div>`:''}</div>`;
}
function roomMembers(){return players.filter(p=>p.area===myArea());}
function nominateHTML(){const area=myArea();const members=roomMembers();if(!area)return '';
  return `<div class="card"><div class="labelrow"><h2>Choose your leader</h2><span class="roomtag ${area.toLowerCase()}">${areaLabel(area)}</span></div><p class="muted small">Talk it over in person. A majority of room votes appoints a new leader.</p><div class="stack">${members.map(p=>`<button class="btn ${me()?.vote===p.uid?'blue':'secondary'} slim" data-vote="${esc(p.uid)}" ${busy?'disabled':''}>${p.uid===room?.leaders?.[area]?'👑 ':''}${esc(p.name)}${p.uid===me()?.vote?' · your vote':''}</button>`).join('')}</div><p class="muted small" style="margin-bottom:0">Current leader: <strong>${esc(nameOf(room?.leaders?.[area]))}</strong></p></div>`;}
function talkUI(){const rem=room.deadlineMs-Date.now();return `<div class="gamewrap"><div class="gamehead"><div><p class="micro">ROUND ${room.round} OF 3 · DISCUSSION</p><h1>Find your <span class="lime">people.</span></h1></div><span class="roomtag ${myArea().toLowerCase()}">You're in ${areaLabel(myArea())}</span></div><div class="twocol"><div class="stack"><div class="card"><p class="roundtitle">Time to make your move</p><div class="timer ${rem<30000?'urgent':''}" id="timer">${fmtClock(rem)}</div><div class="progress"><span id="timer-progress" style="width:${Math.max(0,Math.min(100,rem/duration(room.round)*100))}%"></span></div><p class="muted">Share clues, bluff, and discover which team everyone belongs to. Talk out loud — not in the app.</p>${isHost()?`<button id="finish-talk" class="btn secondary full" ${busy?'disabled':''}>End discussion & choose hostages →</button>`:''}</div>${secretCard()}</div><div class="stack"><div class="card"><div class="labelrow"><h2>${areaLabel(myArea())} · players</h2><span class="roomtag ${myArea().toLowerCase()}">${roomMembers().length} inside</span></div>${peopleCards(roomMembers())}</div>${nominateHTML()}</div></div></div>`;}
function selectUI(){const area=myArea();const leaderId=room?.leaders?.[area];const assigned=selections[area];const need=hostagesNeeded(players.length,room.round);const locked=assigned?.locked&&assigned?.round===room.round;const isMine=isLeader(area);const list=roomMembers().filter(p=>p.uid!==leaderId);
  return `<div class="gamewrap"><div class="gamehead"><div><p class="micro">ROUND ${room.round} OF 3 · HOSTAGE EXCHANGE</p><h1>Who gets <span class="pink">sent away?</span></h1></div><span class="roomtag ${area.toLowerCase()}">${areaLabel(area)}</span></div><div class="twocol"><div class="stack"><div class="card"><h2>${locked?'🔒 Choices locked':'Pick your hostages'}</h2><p class="muted">Each leader must choose <strong>${need} ${need===1?'player':'players'}</strong>. Leaders cannot send themselves. Both rooms lock independently.</p>${isMine&&!locked?`<div class="stack">${list.map(p=>`<label class="choice"><input type="checkbox" data-pick="${esc(p.uid)}" ${chosen.includes(p.uid)?'checked':''}>${esc(p.name)}</label>`).join('')}</div><p class="muted small" id="count">${chosen.length} / ${need} selected</p><button class="btn full" id="lock-picks" ${chosen.length!==need||busy?'disabled':''}>Lock in hostages →</button>`:locked?`<div class="notice success"><strong>Selections locked</strong>${(assigned.picks||[]).map(id=>esc(nameOf(id))).join(', ')}</div>`:`<div class="notice"><strong>Waiting for ${esc(nameOf(leaderId))}</strong>The leader of your room is choosing ${need} ${need===1?'player':'players'}.</div>`}</div>${secretCard()}</div><div class="stack"><div class="card"><h2>Exchange status</h2><div class="stack"><div class="notice ${room.locks?.A?'success':''}"><strong>Room A ${room.locks?.A?'✓ ready':'· deciding'}</strong>${room.locks?.A?'Hostages chosen and locked.':'Waiting for Room A leader.'}</div><div class="notice ${room.locks?.B?'success':''}"><strong>Room B ${room.locks?.B?'✓ ready':'· deciding'}</strong>${room.locks?.B?'Hostages chosen and locked.':'Waiting for Room B leader.'}</div></div>${isHost()?`<div class="divider"></div><button class="btn full" id="exchange" ${busy||!room.locks?.A||!room.locks?.B?'disabled':''}>${room.round===3?'Complete final swap & reveal winner 💥':'Swap players & begin next round →'}</button><p class="muted small">Host: click once both leaders have locked in their choices. You'll receive the same secret role as everyone else.</p>`:'<p class="muted small">The host will swap the selected players when both rooms are ready.</p>'}</div><div class="card"><h2>Now what?</h2><p class="muted">Stay in your current room until the exchange happens. The chosen players will receive a full-screen move instruction.</p></div></div></div></div>`;
}
function resultsUI(){const win=room?.winner||'blue';const result=room?.reveal||{};const roles=result.roles||{};const president=result.presidentRoom||'?';const bomber=result.bomberRoom||'?';const personallyWon=secret?.team===win||(secret?.role==='Gambler'&&secret?.guess===win);return `<div class="gamewrap"><div class="results ${win}"><p class="eyebrow">💥 THE FINAL REVEAL</p><div class="big-emoji">${win==='red'?'💣':'🛡️'}</div><h2>${win==='red'?'RED WINS!':'BLUE WINS!'}</h2><p class="subhead" style="margin:auto">${win==='red'?'The Bomber and President ended in the same room. Boom.':'The President escaped the Bomber. Safe for now.'}</p><div class="resultgrid"><div class="inset"><p class="micro">🏛️ PRESIDENT</p><b>${esc(result.presidentName||'Unknown')}</b><p>${areaLabel(president)}</p></div><div class="inset"><p class="micro">💣 BOMBER</p><b>${esc(result.bomberName||'Unknown')}</b><p>${areaLabel(bomber)}</p></div></div><div class="notice ${personallyWon?'success':'pink'}"><strong>${personallyWon?'🎉 Your side won!':'Your side lost this time'}</strong>${secret?.role==='Gambler'?`You backed ${secret.guess||'no team'}. ${secret.guess===win?'Correct call!':'Better luck next time.'}`:`You were on the ${secret?.team||'?'} team.`}</div><div class="divider"></div><h2 style="font-size:24px;color:white">Everybody's roles</h2><div class="people" style="text-align:left">${players.map(p=>`<div class="person"><div class="avatar">${esc(p.name.slice(0,1).toUpperCase())}</div><div class="person-text"><div class="person-name">${esc(p.name)}</div><div class="person-sub">${esc(roles[p.uid]||'?')} · ${areaLabel(p.area)}</div></div></div>`).join('')}</div><div class="actions" style="justify-content:center;margin-top:22px">${isHost()?`<button class="btn" id="rematch">Rematch with these players ↻</button>`:''}<a class="btn secondary" href="./" style="text-decoration:none">New room →</a></div></div></div>`;}
function overlayHTML(){return movedTo?`<div class="move"><div class="move-panel"><p class="eyebrow">✳ INCOMING HOSTAGE EXCHANGE</p><div class="big-emoji">🚪</div><h2>SWITCH<br><span class="lime">ROOMS!</span></h2><p>You've been moved to <strong>${areaLabel(movedTo)}</strong>. Go there now, and keep your identity secret.</p><button class="btn full" id="dismiss-move">I'm in ${areaLabel(movedTo)} →</button></div></div>`:'';}
function render(){if(!uid){
  if(error){app.innerHTML=`<div class="card" style="max-width:600px;margin:30px auto"><p class="micro">CONNECTION PROBLEM</p><h2>Can't connect to Room Swap</h2><p class="alert">${esc(error)}</p><p class="muted small">Check Anonymous Authentication in your Firebase console and make sure the game's files are uploaded.</p><a href="?reload=3" class="btn" style="text-decoration:none;display:inline-block">Try again ↻</a></div>`;return;}
  if(initSlow){app.innerHTML=`<div class="card" style="max-width:600px;margin:30px auto"><p class="micro">CONNECTION DELAY</p><h2>This is taking longer than normal</h2><p class="muted">${esc(initStage)} The game is still trying to connect. If this remains, check your internet connection, Firebase Authentication and the browser's developer console (F12).</p><div class="actions"><a href="?reload=3" class="btn" style="text-decoration:none">Try again ↻</a><a href="config.js?v=3" class="btn secondary" style="text-decoration:none">Check config.js</a></div></div>`;return;}
  app.innerHTML=`<div class="loading"><div class="spinner"></div><p>${esc(initStage)}</p></div>`;return;
}
  let inner='';if(!roomId)inner=welcome();else if(!room)inner=`<div class="card" style="max-width:560px;margin:45px auto"><h2>${error?'Can't open room':'Opening your invite…'}</h2><p class="muted">${esc(error||'Connecting…')}</p><a href="./" class="btn secondary" style="display:inline-block;text-decoration:none">Home →</a></div>`;else if(!joined)inner=joinUI();else if(room.phase==='lobby')inner=lobby();else if(room.phase==='talk')inner=talkUI();else if(room.phase==='select')inner=selectUI();else if(room.phase==='ended')inner=resultsUI();
  app.innerHTML=(error&&room?`<div class="alert">${esc(error)} <button class="btn secondary slim" id="dismiss-error">Dismiss</button></div>`:'')+inner+overlayHTML();
}
async function create(){const name=document.getElementById('nickname')?.value.trim();if(!name)return toast('Enter your nickname first.');if(name.length>24)return toast('Use a shorter nickname.');localStorage.setItem('room-swap-name',name);await action(async()=>{const id=rand();const game=f.doc(db,ROOT,id);await f.setDoc(game,{hostUid:uid,phase:'lobby',round:0,leaders:{A:'',B:''},deadlineMs:0,winner:'',locks:{A:false,B:false},createdAt:f.serverTimestamp()});await f.setDoc(f.doc(db,ROOT,id,'players',uid),{uid,name,area:'',vote:'',joinedAt:f.serverTimestamp()});location.href=`${location.pathname}?game=${encodeURIComponent(id)}`;});}
async function join(){const name=document.getElementById('nickname')?.value.trim();if(!name)return toast('Enter your nickname first.');localStorage.setItem('room-swap-name',name);await action(async()=>{if(room.phase!=='lobby')throw new Error('This game has already started.');await f.setDoc(refPlayer(uid),{uid,name,area:'',vote:'',joinedAt:f.serverTimestamp()});joined=true;toast('You joined the game!');});}
async function startGame(){await action(async()=>{
  if(!isHost()||room.phase!=='lobby')throw new Error('Only the host can start.');const snap=await f.getDocs(refPlayers());const people=shuffle(snap.docs.map(s=>s.data()));const n=people.length;if(n<6||n>30)throw new Error('This edition supports 6–30 players.');
  const pairs=Math.floor(n/2);const cards=[{role:'President',team:'blue'},{role:'Bomber',team:'red'}];for(let i=0;i<pairs-1;i++)cards.push({role:'Blue Team',team:'blue'},{role:'Red Team',team:'red'});if(n%2)cards.push({role:'Gambler',team:'neutral',guess:''});const roles=shuffle(cards);
  const batch=f.writeBatch(db);for(let i=0;i<n;i++){const person=people[i];batch.update(refPlayer(person.uid),{area:i<Math.ceil(n/2)?'A':'B',vote:''});batch.set(refSecret(person.uid),{uid:person.uid,...roles[i],guess:''});}
  const groupA=people.slice(0,Math.ceil(n/2));const groupB=people.slice(Math.ceil(n/2));
  batch.set(refSelect('A'),{round:1,picks:[],locked:false});batch.set(refSelect('B'),{round:1,picks:[],locked:false});
  batch.update(refRoom(),{phase:'talk',round:1,deadlineMs:Date.now()+duration(1),leaders:{A:groupA[0].uid,B:groupB[0].uid},winner:'',locks:{A:false,B:false},reveal:f.deleteField()});await batch.commit();toast('Roles dealt! The game is on.');
});}
async function vote(id){if(!players.some(p=>p.uid===id&&p.area===myArea()))return;await action(()=>f.updateDoc(refPlayer(uid),{vote:id}));}
async function finishTalk(){await action(async()=>{if(!isHost()||room.phase!=='talk')return;await f.updateDoc(refRoom(),{phase:'select'});chosen=[];toast('Time to choose hostages!');});}
async function lockPicks(){const area=myArea(),need=hostagesNeeded(players.length,room.round);if(!isLeader(area)||room.phase!=='select'||chosen.length!==need)return toast(`Choose exactly ${need}.`);const candidates=roomMembers().filter(p=>p.uid!==uid).map(p=>p.uid);if(!chosen.every(c=>candidates.includes(c)))return toast('Invalid hostage selection.');await action(async()=>{await f.updateDoc(refSelect(area),{round:room.round,picks:[...chosen],locked:true});await f.updateDoc(refRoom(),{[`locks.${area}`]:true});toast('Hostages locked. No changing your mind!');});}
async function guessTeam(team){if(secret?.role!=='Gambler'||!['red','blue'].includes(team)||room.phase==='ended')return;await action(()=>f.updateDoc(refSecret(uid),{guess:team}));}
async function exchange(){await action(async()=>{
  if(!isHost()||room.phase!=='select')return;const [as,bs]=await Promise.all([f.getDoc(refSelect('A')),f.getDoc(refSelect('B'))]);const aa=as.data(),bb=bs.data();if(!aa?.locked||!bb?.locked||aa.round!==room.round||bb.round!==room.round)throw new Error('Wait until both rooms are ready.');
  const needed=hostagesNeeded(players.length,room.round);if(aa.picks.length!==needed||bb.picks.length!==needed)throw new Error('Both rooms must send the required number of hostages.');
  const picksA=aa.picks,picksB=bb.picks;const inArea=(id,area)=>players.some(p=>p.uid===id&&p.area===area);
  if(!picksA.every(id=>inArea(id,'A')&&id!==room.leaders.A)||!picksB.every(id=>inArea(id,'B')&&id!==room.leaders.B))throw new Error('Some chosen players are no longer eligible.');
  const batch=f.writeBatch(db);for(const id of picksA)batch.update(refPlayer(id),{area:'B',vote:''});for(const id of picksB)batch.update(refPlayer(id),{area:'A',vote:''});
  for(const p of players)if(![...picksA,...picksB].includes(p.uid)&&p.vote)batch.update(refPlayer(p.uid),{vote:''});
  if(room.round<3){const next=room.round+1;batch.set(refSelect('A'),{round:next,picks:[],locked:false});batch.set(refSelect('B'),{round:next,picks:[],locked:false});batch.update(refRoom(),{round:next,phase:'talk',deadlineMs:Date.now()+duration(next),locks:{A:false,B:false}});}
  else{const snap=await f.getDocs(f.collection(db,ROOT,roomId,'secrets'));const roleDocs=snap.docs.map(s=>s.data());const pres=roleDocs.find(r=>r.role==='President');const bomb=roleDocs.find(r=>r.role==='Bomber');if(!pres||!bomb)throw new Error('Missing game roles.');
    const newArea=id=>picksA.includes(id)?'B':picksB.includes(id)?'A':players.find(p=>p.uid===id)?.area;
    const presidentRoom=newArea(pres.uid),bomberRoom=newArea(bomb.uid),winner=presidentRoom===bomberRoom?'red':'blue';const roles=Object.fromEntries(roleDocs.map(r=>[r.uid,r.role]));
    batch.update(refRoom(),{phase:'ended',winner,reveal:{presidentRoom,bomberRoom,presidentName:nameOf(pres.uid),bomberName:nameOf(bomb.uid),roles}});
  }
  await batch.commit();chosen=[];toast(room.round===3?'The final reveal is here!':'Hostages swapped. Next round!');
});}
async function rematch(){await action(async()=>{if(!isHost())return;const batch=f.writeBatch(db);for(const p of players)batch.update(refPlayer(p.uid),{area:'',vote:''});batch.update(refRoom(),{phase:'lobby',round:0,deadlineMs:0,winner:'',locks:{A:false,B:false},leaders:{A:'',B:''},reveal:f.deleteField()});await batch.commit();roleVisible=false;chosen=[];movedTo='';toast('Rematch lobby is open.');});}
function ticks(){if(!room)return;
  const el=document.getElementById('timer');if(el&&room.phase==='talk'){const rem=room.deadlineMs-Date.now();el.textContent=fmtClock(rem);el.classList.toggle('urgent',rem<30000);const bar=document.getElementById('timer-progress');if(bar)bar.style.width=`${Math.max(0,Math.min(100,100*rem/duration(room.round)))}%`;
    if(rem<=0&&isHost()&&!autoEnding){autoEnding=true;f.updateDoc(refRoom(),{phase:'select'}).catch(fail).finally(()=>{autoEnding=false;});}
  }
}
app.addEventListener('click',async e=>{
  const btn=e.target.closest('button');if(!btn)return;const id=btn.id;
  if(id==='create')return create();if(id==='join')return join();if(id==='start')return startGame();if(id==='finish-talk')return finishTalk();if(id==='lock-picks')return lockPicks();if(id==='exchange')return exchange();if(id==='rematch')return rematch();
  if(id==='show-role'){roleVisible=true;render();return;}if(id==='hide-role'){roleVisible=false;render();return;}
  if(id==='dismiss-move'){movedTo='';render();return;}if(id==='dismiss-error'){error='';render();return;}
  if(id==='copy'){try{await navigator.clipboard.writeText(invite);toast('Invite link copied!');}catch{const input=document.getElementById('invite-link');input?.select();document.execCommand('copy');toast('Invite link copied!');}return;}
  if(id==='share'){if(navigator.share){try{await navigator.share({title:'Join Room Swap',text:'Come play Room Swap with us!',url:invite});}catch{}}else{await navigator.clipboard.writeText(invite);toast('Invite link copied!');}return;}
  if(btn.dataset.vote)return vote(btn.dataset.vote);if(btn.dataset.guess)return guessTeam(btn.dataset.guess);
});
app.addEventListener('change',e=>{const cb=e.target.closest('[data-pick]');if(!cb)return;const id=cb.dataset.pick;if(cb.checked){chosen=[...new Set([...chosen,id])];}else chosen=chosen.filter(x=>x!==id);const need=hostagesNeeded(players.length,room.round);const count=document.getElementById('count');if(count)count.textContent=`${chosen.length} / ${need} selected`;const lock=document.getElementById('lock-picks');if(lock)lock.disabled=chosen.length!==need||busy;});
setInterval(ticks,500);
init();
