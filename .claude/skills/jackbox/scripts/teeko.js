// Unified Tee K.O. autopilot. Detects the live phase each tick and acts instantly:
//  - DRAW  : Opus designs a bold graphic -> replayed as human-jittered mouse strokes -> submit
//  - SLOGAN: pre-generated funny-slogan queue -> submit continuously
//  - VOTE  : text-first (instant Haiku judgment); CDP-screenshot + Sonnet vision for image-only shirts
// Runs locally in a tight loop; never steals window focus. Heartbeat every 8s.
// Needs ANTHROPIC_API_KEY in env. Logs to stdout. Stop by killing the process.
const { chromium } = require('playwright');
const API_KEY = process.env.ANTHROPIC_API_KEY;
const log = m => process.stdout.write(`[${new Date().toISOString()}] ${m}\n`);

const COLOR_RGB = { black:[0,0,0], white:[255,255,255], red:[230,30,30], orange:[240,140,20],
  yellow:[245,220,30], green:[40,180,70], blue:[40,90,220], purple:[140,50,200], pink:[240,110,190], brown:[140,80,40] };
const nz = px => (Math.random()-0.5)*px;
const rjObj = t => { const m=t.match(/\{[\s\S]*\}/); return JSON.parse(m?m[0]:t); };
const rjArr = t => { const m=t.match(/\[[\s\S]*\]/); return JSON.parse(m?m[0]:t); };

async function claude(model, system, content, maxTokens){
  const r = await fetch('https://api.anthropic.com/v1/messages',{method:'POST',
    headers:{'x-api-key':API_KEY,'anthropic-version':'2023-06-01','content-type':'application/json'},
    body:JSON.stringify({model,max_tokens:maxTokens,system,messages:[{role:'user',content}]})});
  if(!r.ok) throw new Error(`API ${r.status}: ${(await r.text()).slice(0,120)}`);
  const d = await r.json(); return d.content[0].text;
}

// ---- content generators ----
const DESIGN_SYS =
  "You design BOLD, funny, instantly-readable t-shirt graphics for Tee K.O., as simple line art with ONE clear central subject. "+
  "Iconic + absurd (skull in party hat, cat DJ with headphones, angry coffee cup, raccoon CEO, ghost with balloon, T-Rex flexing tiny arms). "+
  'Output STRICT JSON: { "concept":"<=6 words", "strokes":[ {"color":"black|white|red|orange|yellow|green|blue|purple|pink|brown","points":[[x,y],...]} ] }. '+
  "Normalized 0..1, origin top-left, y down, keep inside 0.12..0.88, centered. 6-16 strokes, each a continuous pen line (>=2 pts; curves=many pts). "+
  "Bold simple shapes, no tiny detail, mostly black with 1-3 accents, no big fills.";
async function design(){ return rjObj(await claude('claude-opus-4-8', DESIGN_SYS, 'Design one bold funny t-shirt graphic. JSON only.', 1500)); }

// Same comedic principles as quiplash.js -- specificity, absurd, smart-stupid, relatable darkness, punchy.
const SLOGAN_SYS =
  "You write SLOGANS for t-shirts in Tee K.O.; funniest shirt wins the room's vote. Principles: specificity > generic; commit to the absurd; "+
  "smart-stupid juxtaposition; relatable darkness (debt, your ex, the DMV, burnout, existential dread, HR); punchy with the funniest word last. "+
  "The bar (aim here, don't copy): 'A cupholder shaped like the middle class' -- a mundane thing weaponized into a socioeconomic gut-punch. "+
  "Feel like real absurd merch; mix fake-motivational, cursed-corporate, doomer, weird-flex. "+
  "No clichés, hashtags, emoji, or quotes. Each <=45 chars. Output STRICT JSON: array of strings only.";
async function genSlogans(n){ return rjArr(await claude('claude-opus-4-8', SLOGAN_SYS,
  `Write ${n} distinct genuinely funny t-shirt slogans. JSON array only.`, 1200))
  .map(s=>String(s).replace(/^["'`]|["'`]$/g,'').trim()).filter(Boolean).map(s=>s.slice(0,45)); }

// ---- drawing primitives ----
async function pickColor(page, name){
  const want = COLOR_RGB[name]||COLOR_RGB.black;
  const handle = await page.evaluateHandle((want)=>{
    const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
    const parse=s=>{const m=s&&s.match(/rgba?\(([^)]+)\)/);if(!m)return null;const p=m[1].split(',').map(Number);return[p[0],p[1],p[2]];};
    let best=null,bd=1e9;
    for(const el of document.querySelectorAll('button,div,li,span')){const r=el.getBoundingClientRect();
      if(r.width<14||r.width>70||r.height<14||r.height>70)continue;
      const bg=parse(getComputedStyle(el).backgroundColor);if(!bg)continue;
      const d=dist(bg,want);if(d<bd){bd=d;best=el;}}
    return bd<60?best:null;
  }, want);
  const el=handle.asElement(); if(el){ try{ await el.click({timeout:700}); }catch{} }
}
async function drawStroke(page, ox, oy, w, h, points){
  const map=p=>[ox+p[0]*w+nz(1.5), oy+p[1]*h+nz(1.5)];
  let [x,y]=map(points[0]); await page.mouse.move(x,y); await page.mouse.down();
  for(let i=1;i<points.length;i++){ const [tx,ty]=map(points[i]);
    // interpolate each segment into small jittered steps for a hand-drawn wobble
    const segs=Math.max(2,Math.round(Math.hypot(tx-x,ty-y)/8));
    for(let s=1;s<=segs;s++){ await page.mouse.move(x+(tx-x)*s/segs+nz(1.2), y+(ty-y)*s/segs+nz(1.2)); }
    x=tx; y=ty; }
  await page.mouse.up();
}
async function doDrawing(page, rect){
  const plan = await design();
  log(`DRAW: ${plan.concept} (${plan.strokes.length} strokes)`);
  let last=null;
  for(const st of plan.strokes){
    if(st.color&&st.color!==last){ await pickColor(page, st.color); last=st.color; }
    const pts=(st.points||[]).filter(p=>Array.isArray(p)&&p.length===2);
    if(pts.length>=2) await drawStroke(page, rect.x, rect.y, rect.w, rect.h, pts);
    await page.waitForTimeout(30);
  }
}

// ---- vision vote (fallback for image-only shirts) ----
async function visionVote(page, cdp, votes){
  const { data } = await cdp.send('Page.captureScreenshot', { format:'png' });
  const orient = (Math.abs(votes[0].cx-votes[1].cx) >= Math.abs(votes[0].cy-votes[1].cy)) ? 'LR' : 'TB';
  const labelA = orient==='LR'?'LEFT':'TOP', labelB = orient==='LR'?'RIGHT':'BOTTOM';
  const sorted = orient==='LR' ? [...votes].sort((a,b)=>a.cx-b.cx) : [...votes].sort((a,b)=>a.cy-b.cy);
  const out = (await claude('claude-sonnet-4-6',
    'You judge a Tee K.O. shirt battle. Reply with exactly one word: '+labelA+' or '+labelB+' -- whichever t-shirt is funnier/better.',
    [{type:'image',source:{type:'base64',media_type:'image/png',data}},
     {type:'text',text:`Two shirts are shown. Which is funnier: ${labelA} or ${labelB}? One word.`}], 5)).toUpperCase();
  const pick = out.includes(labelB) ? sorted[1] : sorted[0];
  await page.mouse.click(pick.cx, pick.cy);
  log(`VOTE(vision): ${out.trim()} -> ${Math.round(pick.cx)},${Math.round(pick.cy)}`);
}

// ---- DOM phase probe ----
async function probe(page){
  return await page.evaluate(()=>{
    const vis=el=>{const r=el.getBoundingClientRect();const s=getComputedStyle(el);
      return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!el.disabled;};
    const canvasEl=[...document.querySelectorAll('canvas')].find(c=>{const r=c.getBoundingClientRect();return r.width>200&&r.height>200;});
    let canvas=null, blank=null;
    if(canvasEl){ const r=canvasEl.getBoundingClientRect(); canvas={x:r.x,y:r.y,w:r.width,h:r.height};
      try{ const cx=canvasEl.getContext('2d'); if(cx){ const s=80;
        const id=cx.getImageData(0,0,Math.min(canvasEl.width,400),Math.min(canvasEl.height,400)).data;
        let dark=0,n=0; for(let i=0;i<id.length;i+=4*s){ n++; if(id[i]<240||id[i+1]<240||id[i+2]<240) dark++; }
        blank=(dark/n)<0.01; } }catch(e){ blank=null; }
    }
    const submitDraw=document.querySelector('#awshirt-submitdrawing');
    const textInput=[...document.querySelectorAll('input[type=text],textarea')].filter(vis).find(i=>i.id!=='roomcode'&&i.id!=='username');
    const submitBtn=[...document.querySelectorAll('button')].filter(vis).find(b=>/submit|send|done/i.test(b.id)||/^(SEND|SUBMIT|DONE|OK)$/i.test((b.innerText||'').trim()));
    const voteEls=[...document.querySelectorAll('button,[role=button],img,div')].filter(el=>vis(el)&&/vote/i.test((el.id+' '+el.className).toString()))
      .map(el=>{const r=el.getBoundingClientRect();return{cx:r.x+r.width/2,cy:r.y+r.height/2,a:r.width*r.height,txt:(el.innerText||'').trim().slice(0,60)};})
      .filter(v=>v.a>5000);
    return {
      canvas, blank,
      hasSubmitDraw: !!(submitDraw && vis(submitDraw)),
      textInputSel: textInput?(textInput.id?('#'+textInput.id):'textarea'):null,
      submitBtnId: submitBtn?submitBtn.id:null,
      votes: voteEls.slice(0,2),
      text: document.body.innerText.replace(/\s+/g,' ').trim().slice(0,80),
    };
  });
}

(async ()=>{
  if(!API_KEY){ log('FATAL no ANTHROPIC_API_KEY'); process.exit(1); }
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find(p=>p.url().includes('jackbox'))||ctx.pages()[0];
  const cdp = await ctx.newCDPSession(page);
  log('Tee K.O. autopilot connected');

  let queue = [];
  (async()=>{ try{ queue = await genSlogans(30); log('slogan queue: '+queue.length); }catch(e){ log('slogan gen fail '+e.message); } })();

  let drewThisCanvas=false, lastSlogan=0, votedSig='', lastHB=0;
  while(true){
    try{
      const st = await probe(page);

      // heartbeat so we can see it's alive and what phase it sees
      if(Date.now()-lastHB>8000){ lastHB=Date.now();
        const phase = st.votes.length>=2?'VOTE':(st.canvas&&st.hasSubmitDraw?'DRAW':(st.textInputSel&&st.submitBtnId?'SLOGAN':'idle'));
        log(`hb phase=${phase} votes=${st.votes.length} canvas=${!!st.canvas} text="${st.text.slice(0,40)}"`); }

      // VOTE: text-first (instant via Haiku), vision fallback for image-only shirts
      if(st.votes.length>=2){
        const [a,b]=st.votes;
        const sig = (a.txt||a.cx+','+a.cy)+'||'+(b.txt||b.cx+','+b.cy);
        if(sig!==votedSig){ votedSig=sig;
          try{
            if(a.txt && b.txt && a.txt.length>1 && b.txt.length>1){
              const out=(await claude('claude-haiku-4-5-20251001',
                'You judge a Tee K.O. shirt battle by slogan. Reply with exactly one letter: A or B -- the funnier one.',
                `A: ${a.txt}\nB: ${b.txt}`, 5)).toUpperCase();
              const pick = (out.includes('B')&&!out.includes('A')) ? b : a;
              await page.mouse.click(pick.cx, pick.cy);
              log(`VOTE(text): "${pick.txt}"  (over "${(pick===a?b:a).txt}")`);
            } else {
              await visionVote(page, cdp, st.votes);
            }
          }catch(e){ log('vote fail '+e.message.split('\n')[0]); }
        }
      }
      // DRAW
      else if(st.canvas && st.hasSubmitDraw){
        if(st.blank===true) drewThisCanvas=false;       // fresh blank canvas -> ready to draw again
        if(!drewThisCanvas){
          drewThisCanvas=true;
          try{ await doDrawing(page, st.canvas); await page.click('#awshirt-submitdrawing',{timeout:2500}); log('submitted drawing'); }
          catch(e){ log('draw/submit fail '+e.message.split('\n')[0]); }
        }
      }
      // SLOGAN
      else if(st.textInputSel && st.submitBtnId){
        if(queue.length===0){ try{ queue = await genSlogans(20); log('refilled slogans '+queue.length); }catch{} }
        if(queue.length && Date.now()-lastSlogan>700){
          const s=queue.shift(); lastSlogan=Date.now();
          try{ await page.fill(st.textInputSel,s,{timeout:1500}); await page.click('#'+st.submitBtnId,{timeout:1500}); log('SLOGAN: '+s); }
          catch(e){ log('slogan submit fail '+e.message.split('\n')[0]); }
        }
      }

      if(!st.canvas) drewThisCanvas=false;
    }catch(e){ log('loop err '+e.message.split('\n')[0]); }
    await new Promise(r=>setTimeout(r, 600));
  }
})().catch(e=>{ log('FATAL '+e.message); process.exit(1); });
