/* Record real final app pixels. No DOM overlays, subtitle tracks or manufactured frames. */
import fs from 'node:fs/promises';import path from 'node:path';import crypto from 'node:crypto';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';import {spawn} from 'node:child_process';import {once} from 'node:events';
const root=process.cwd(),out=path.join(root,'outputs/final_overnight_20261015'),qa=path.join(out,'qa'),require=createRequire(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json')),{chromium}=require('playwright');
const mode=process.argv[2]||'main',dry=mode.startsWith('dry'),duration=mode.includes('compact')?30:75,fps=30,delay=ms=>new Promise(r=>setTimeout(r,Math.max(0,ms))),hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const contract=JSON.parse(await fs.readFile('work/final_overnight/deck-contract.json','utf8'));
const frozenNames=['app/index.html','app/cape_workspace.js','app/cape_workspace.css','app/cape_report.js','app/parametric.js','app/assessment_assistant.js','INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pptx','SUNDAY_10_MIN_SCRIPT.md','VIDEO_LIVE_NARRATION.md','Q_AND_A_20.md'];
const hashes=Object.fromEntries(await Promise.all(frozenNames.map(async n=>[n,hash(await fs.readFile(path.join(out,n)))])));
const frozen={build_id:contract.build_id,frozen_utc:new Date().toISOString(),files:hashes};
if(!dry)await fs.writeFile(path.join(qa,'video-freeze-'+duration+'.json'),JSON.stringify(frozen,null,2));
const b=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-background-networking']});let encoder,cdp;
const actions=[],errors=[],network=[];let start=0;
try{
 const c=await b.newContext({viewport:{width:1920,height:1080},deviceScaleFactor:1,acceptDownloads:true});await c.route(/^https?:/,r=>{network.push(r.request().url());return r.abort();});
 const p=await c.newPage();p.setDefaultTimeout(5000);p.on('pageerror',e=>errors.push(e.message));await p.goto(pathToFileURL(path.join(out,'app/index.html')).href);await p.waitForFunction(()=>window.ShieldAssistantUI);
 const state=()=>p.evaluate(()=>ShieldWorkspace.getState());const initial=await state();assert.equal(initial.build_id,contract.build_id);assert.equal(initial.assessment.height_fraction,contract.canonical_result.height_fraction);
 async function scroll(sel){await p.locator(sel).evaluate(e=>e.scrollIntoView({behavior:'smooth',block:'center'}));await delay(dry?100:duration===30?180:350);}
 async function focus(sel){await scroll(sel);await p.locator(sel).focus();const box=await p.locator(sel).boundingBox();if(box)await p.mouse.move(box.x+box.width/2,box.y+box.height/2,{steps:14});}
 async function click(sel){await focus(sel);await p.locator(sel).click();}
 async function choose(sel,value){await focus(sel);await p.locator(sel).selectOption(value);}
 async function fill(sel,value){await focus(sel);await p.locator(sel).fill(value);}
 const stage=n=>click('[data-stage="'+n+'"]');
 async function action(name){
  if(name==='select'){await choose('#case-select','cape_clear');await click('.leaflet-control-zoom-in');await delay(dry?100:350);await click('#fit-map');}
  if(name==='history'){await stage(1);if(duration===75){await click('#layer-menu summary');await click('[data-layer="historical"]');await click('[data-layer="historical"]');await click('[data-layer="scenario"]');await click('[data-layer="scenario"]');await click('#layer-menu summary');}}
  if(name==='year'){await choose('#evidence-year','2019');}
  if(name==='conflict'){await choose('#evidence-year','all');await scroll('.ref-compare');}
  if(name==='condition'){await click('[data-habitat-tab="condition"]');await scroll('.trend-chart');}
  if(name==='risk'){await click('[data-habitat-tab="risk"]');await scroll('.driver-grid');}
  if(name==='filter'){await click('[data-habitat-tab="history"]');await choose('#evidence-year','1994');}
  if(name==='wave'){if(await p.locator('#evidence-year').count())await choose('#evidence-year','all');await stage(2);await choose('#habitat-mode','without');}
  if(name==='with'){await choose('#habitat-mode','with');await click('#pin-scenario');}
  if(name==='depth'){await fill('[data-input="water_level_m"]','2');await scroll('#scenario-comparison');}
  if(name==='restore-wave'){await fill('[data-input="water_level_m"]','0');}
  if(name==='cost'){await stage(3);await fill('[data-input="frontage_m"]','150');await scroll('#economic-result');}
  if(name==='share'){await click('[data-share="25"]');await scroll('#economic-result');}
  if(name==='restore-cost'){await click('#reset-inputs');await scroll('#economic-result');}
  if(name==='bio'){await stage(4);await choose('#bio-class','Phaeophyceae');}
  if(name==='quality'){await choose('#bio-quality','no-land');await scroll('#bio-results');}
  if(name==='restore-bio'){await choose('#bio-class','all');await choose('#bio-quality','all');}
  if(name==='priority'){await choose('#priority-filter','P1');await click('[data-priority-map="P1"]');await scroll('#priorities');}
  if(name==='ask'){await click('#ask-open');await fill('#ask-question','What does the 8.43% result mean?');await click('#ask-form button');assert.match(await p.locator('#ask-answer').textContent(),/8.42954%/);}
  if(name==='citations'){await click('#ask-answer details:first-of-type summary');}
  if(name==='boundary'){await scroll('#ask-answer details[open]:last-of-type');}
  if(name==='report'){await click('#ask-close');await stage(5);await click('#generate-report');await p.frameLocator('#report-preview').locator('#section-12').waitFor({state:'attached'});const downloaded=p.waitForEvent('download');await click('#save-report');await (await downloaded).saveAs(path.join(qa,'VIDEO_DOWNLOADED_'+duration+'.html'));const json=p.waitForEvent('download');await click('#save-report-data');await (await json).saveAs(path.join(qa,'VIDEO_DOWNLOADED_'+duration+'.json'));}
  const current=await state();actions.push({name,actual_seconds:start?(performance.now()-start)/1000:0,state:current});
  if(dry)await p.screenshot({path:path.join(qa,'video-dry-'+name+'.png')});
 }
 const main=[[5,'select'],[12,'history'],[15,'year'],[17,'conflict'],[20,'condition'],[24,'risk'],[27,'filter'],[30,'wave'],[33,'with'],[35,'depth'],[39,'restore-wave'],[40,'cost'],[44,'share'],[47,'restore-cost'],[49,'bio'],[52,'quality'],[55,'restore-bio'],[58,'priority'],[64,'ask'],[67,'citations'],[69,'boundary'],[71,'report']];
 const compact=[[0,'select'],[3,'history'],[5,'conflict'],[6.5,'condition'],[8,'wave'],[9.5,'with'],[11,'depth'],[12.5,'restore-wave'],[13,'cost'],[14.5,'share'],[16,'restore-cost'],[17,'bio'],[18.5,'restore-bio'],[20,'priority'],[22,'ask'],[24,'citations'],[26,'report']];
 if(dry){for(const [,name]of duration===75?main:compact)await action(name);assert.deepEqual(errors,[]);assert.deepEqual(network,[]);await fs.writeFile(path.join(qa,'video-dry-run-'+duration+'.json'),JSON.stringify({status:'PASS',build_id:contract.build_id,actions,errors,network},null,2));console.log('Dry route PASS; no video recorded');}
 else{
  cdp=await c.newCDPSession(p);let latest=await p.screenshot({type:'jpeg',quality:94}),incoming=0;cdp.on('Page.screencastFrame',e=>{latest=Buffer.from(e.data,'base64');incoming++;void cdp.send('Page.screencastFrameAck',{sessionId:e.sessionId});});await cdp.send('Page.startScreencast',{format:'jpeg',quality:94,maxWidth:1920,maxHeight:1080,everyNthFrame:1});
  const file=path.join(out,'DEMO_'+duration+'_SECONDS.mp4');encoder=spawn(path.join(root,'work/story_20261014/ffmpeg.exe'),['-hide_banner','-loglevel','warning','-f','image2pipe','-vcodec','mjpeg','-framerate',String(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart','-y',file],{windowsHide:true,stdio:['pipe','ignore','pipe']});let log='';encoder.stderr.on('data',d=>log+=d);const ended=once(encoder,'close');start=performance.now();const started=new Date().toISOString();let actionError;
  const run=(async()=>{for(const [at,name]of duration===75?main:compact){await delay(at*1000-(performance.now()-start));actions.push({scheduled_seconds:at,name});await action(name);}})().catch(e=>{actionError=e;});
  for(let frame=0;frame<duration*fps;frame++){await delay(frame*1000/fps-(performance.now()-start));if(!encoder.stdin.write(latest))await once(encoder.stdin,'drain');}
  encoder.stdin.end();await run;const [code]=await ended;if(code!==0)throw Error(log);if(actionError)throw actionError;await cdp.send('Page.stopScreencast');
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);const final=await state();assert.deepEqual(final.inputs,contract.inputs);assert.equal(final.assessment.height_fraction,contract.canonical_result.height_fraction);assert.equal(final.bioClass,'all');assert.equal(final.bioQuality,'all');assert.ok(actions.at(-1).actual_seconds<duration-0.4,'Final report was not visible before the film ended');
  for(const [n,h]of Object.entries(hashes))assert.equal(hash(await fs.readFile(path.join(out,n))),h,'Frozen artifact changed '+n);
  const bytes=await fs.readFile(file);await fs.writeFile(file+'.json',JSON.stringify({status:'RECORDED',file:path.basename(file),build_id:contract.build_id,started_utc:started,presentation_frozen_utc:frozen.frozen_utc,sha256:hash(bytes),bytes:bytes.length,duration_seconds:duration,width:1920,height:1080,fps,frames:duration*fps,source_screencast_frames:incoming,audio:false,subtitles:false,overlays:false,method:'Actual final Chrome file-mode application. CDP frames sampled in real time, H.264 encoded without graphic overlays or content replacement.',cursor_limitation:'OS cursor is not included by CDP. Windows capture helper approval timed out. Actual focus, button, selection and result states are shown; no artificial cursor added.',initial,final,actions,errors,network},null,2));console.log(JSON.stringify({status:'RECORDED',duration,bytes:bytes.length,incoming,build_id:contract.build_id,last_action_seconds:actions.at(-1).actual_seconds}));
 }
}finally{encoder?.stdin?.end();await b.close();}
