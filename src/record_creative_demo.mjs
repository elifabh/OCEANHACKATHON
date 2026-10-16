/* Real unchanged app, native focus feedback, continuous real-time capture.
   Camera crop/zoom uses only captured pixels. No cursor, subtitles, fake values or UI overlays. */
import fs from 'node:fs/promises';import path from 'node:path';import crypto from 'node:crypto';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';import {spawn} from 'node:child_process';import {once} from 'node:events';
const root=process.cwd(),out=path.join(root,'outputs/final_creative_20261015'),app=path.join(root,'outputs/final_overnight_20261015/app'),qa=path.join(out,'qa');
const req=createRequire(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json')),{chromium}=req('playwright'),sharp=req('sharp');
sharp.concurrency(2);const mode=process.argv[2]||'main',dry=mode.startsWith('dry'),duration=mode.includes('compact')?30:75,fps=30,wait=ms=>new Promise(r=>setTimeout(r,Math.max(0,ms))),hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const contract=JSON.parse(await fs.readFile(path.join(out,'presentation_contract.json'),'utf8'));
const freezeNames=['INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx','SUNDAY_10_MIN_SCRIPT.md','VIDEO_LIVE_NARRATION.md','Q_AND_A_20.md'];
const freeze={build_id:contract.build_id,frozen_utc:new Date().toISOString(),files:Object.fromEntries(await Promise.all(freezeNames.map(async n=>[n,hash(await fs.readFile(path.join(out,n)))]))),app_sha256:hash(await fs.readFile(path.join(app,'index.html')))};
const b=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-background-networking']});
let encoder,cdp,start=0;const actions=[],errors=[],network=[],focusChecks=[],cameras=[];let camera={zoom:1,x:960,y:540},target={...camera};
try{
 const c=await b.newContext({viewport:{width:1440,height:810},deviceScaleFactor:4/3,acceptDownloads:true});await c.route(/^https?:/,r=>{network.push(r.request().url());return r.abort()});const p=await c.newPage();p.setDefaultTimeout(7000);p.on('pageerror',e=>errors.push(e.message));
 const downloadSession=await c.newCDPSession(p);await downloadSession.send('Browser.setDownloadBehavior',{behavior:'allowAndName',downloadPath:qa,eventsEnabled:true});
 await p.goto(pathToFileURL(path.join(app,'index.html')).href);await p.waitForFunction(()=>window.ShieldAssistantUI);
 const state=()=>p.evaluate(()=>ShieldWorkspace.getState()),initial=await state();assert.equal(initial.build_id,contract.build_id);
 async function look(sel,zoom=1.23){const box=await p.locator(sel).boundingBox();if(box)target={zoom,x:(box.x+box.width/2)*4/3,y:(box.y+box.height/2)*4/3};}
 async function scroll(sel){await p.locator(sel).evaluate(e=>e.scrollIntoView({behavior:'smooth',block:'center'}));await wait(dry?60:duration===30?110:280);}
 async function focus(sel){await scroll(sel);await p.keyboard.press('Tab');await p.locator(sel).focus();await look(sel);const proof=await p.locator(sel).evaluate(e=>({visible:e.matches(':focus-visible'),outline:getComputedStyle(e).outline,tag:e.tagName}));focusChecks.push({selector:sel,...proof});assert.ok(proof.visible,'Actual keyboard focus must be visible: '+sel);await wait(dry?30:duration===30?90:260);}
 async function click(sel){await focus(sel);await p.locator(sel).click();if(await p.locator(sel).count()){await p.keyboard.press('Tab');await p.locator(sel).focus();}}
 async function choose(sel,v){await focus(sel);await p.locator(sel).selectOption(v);}
 async function fill(sel,v){await focus(sel);await p.locator(sel).fill(v);}
 const stage=n=>click('[data-stage="'+n+'"]');
 async function action(name){
  if(name==='select'){await choose('#case-select','cape_clear');await click('.leaflet-control-zoom-in');await wait(dry?50:250);await click('#fit-map');target={zoom:1,x:960,y:540};}
  if(name==='history'){await stage(1);await click('#layer-menu summary');await click('[data-layer="historical"]');await wait(dry?50:350);await click('[data-layer="historical"]');await click('#layer-menu summary');}
  if(name==='date'){await choose('#evidence-year','2019');await look('#evidence-year');}
  if(name==='conflict'){await choose('#evidence-year','all');await scroll('.ref-compare');await look('.ref-compare',1.3);}
  if(name==='condition'){await click('[data-habitat-tab="condition"]');await scroll('.trend-chart');await look('.trend-chart',1.25);}
  if(name==='risk'){await click('[data-habitat-tab="risk"]');await scroll('.driver-grid');await look('.driver-grid',1.23);}
  if(name==='without'){await stage(2);await choose('#habitat-mode','without');await look('#physical-result',1.25).catch(()=>{});}
  if(name==='with'){await choose('#habitat-mode','with');await click('#pin-scenario');}
  if(name==='depth'){await fill('[data-input="water_level_m"]','2');await scroll('#scenario-comparison');await look('#scenario-comparison',1.28);}
  if(name==='restore-wave'){await fill('[data-input="water_level_m"]','0');}
  if(name==='cost'){await stage(3);await fill('[data-input="frontage_m"]','150');await scroll('#economic-result');await look('#economic-result',1.3);}
  if(name==='restore-cost'){await click('#reset-inputs');await scroll('#economic-result');await look('#economic-result',1.25);}
  if(name==='bio'){await stage(4);await choose('#bio-class','Phaeophyceae');await scroll('#bio-results');await look('#bio-results',1.25);}
  if(name==='priority'){await choose('#bio-class','all');await choose('#priority-filter','P1');await click('[data-priority-map="P1"]');target={zoom:1.08,x:960,y:540};}
  if(name==='ask'){await click('#ask-open');await focus('#ask-question');await p.locator('#ask-question').pressSequentially('What does the 8.43% result mean?',{delay:dry?1:duration===30?7:24});await click('#ask-form button');await scroll('#ask-answer');await look('#ask-answer',1.32);assert.match(await p.locator('#ask-answer').textContent(),/8.42954%/);}
  if(name==='citations'){await click('#ask-answer details:first-of-type summary');await look('#ask-answer',1.32);}
  if(name==='boundary'){await scroll('#ask-answer details[open]:last-of-type');await look('#ask-answer details[open]:last-of-type',1.32);}
  if(name==='report'){await click('#ask-close');await stage(5);await click('#generate-report');await p.frameLocator('#report-preview').locator('#section-12').waitFor({state:'attached'});target={zoom:1.15,x:1350,y:530};}
  if(name==='download'){const dl=p.waitForEvent('download');await click('#save-report');await(await dl).saveAs(path.join(qa,'DEMO_REPORT_'+duration+'.html'));const js=p.waitForEvent('download');await click('#save-report-data');await(await js).saveAs(path.join(qa,'DEMO_REPORT_'+duration+'.json'));await scroll('#report-preview');await look('#report-preview',1.18);}
  const current=await state();actions.push({name,seconds:start?(performance.now()-start)/1000:0,state:current,camera_target:{...target}});
  if(dry)await p.screenshot({path:path.join(qa,'route-'+duration+'-'+name+'.png')});
 }
 const route=[[3,'select'],[7,'history'],[11,'date'],[14,'conflict'],[17,'condition'],[22,'risk'],[26,'without'],[29,'with'],[32,'depth'],[37,'restore-wave'],[39,'cost'],[45,'restore-cost'],[49,'bio'],[53,'priority'],[57,'ask'],[63,'citations'],[66,'boundary'],[69,'report'],[72,'download']];
 const compact=[[1,'select'],[4,'history'],[7,'conflict'],[9,'without'],[11,'with'],[13,'depth'],[16,'restore-wave'],[17,'cost'],[20,'restore-cost'],[22,'ask'],[25,'report'],[27,'download']];
 if(dry){for(const [,name]of(duration===75?route:compact))await action(name);await fs.writeFile(path.join(qa,'route-'+duration+'.json'),JSON.stringify({status:'PASS',build_id:contract.build_id,actions,focusChecks,errors,network},null,2));console.log('Dry interaction route passed');}
 else{
  await fs.writeFile(path.join(qa,'video-freeze-'+duration+'.json'),JSON.stringify(freeze,null,2));
  let latest=await p.screenshot({type:'jpeg',quality:94}),incoming=0;cdp=await c.newCDPSession(p);
  cdp.on('Page.screencastFrame',e=>{latest=Buffer.from(e.data,'base64');incoming++;void cdp.send('Page.screencastFrameAck',{sessionId:e.sessionId});});await cdp.send('Page.startScreencast',{format:'jpeg',quality:94,maxWidth:1920,maxHeight:1080,everyNthFrame:1});
  while(!incoming)await wait(30);
  const snapshots=[];
  start=performance.now();const started=new Date().toISOString();let fail;
  const journey=(async()=>{for(const [at,name]of(duration===75?route:compact)){await wait(at*1000-(performance.now()-start));await action(name);}})().catch(e=>fail=e);
  for(let frame=0;frame<duration*fps;frame++){
   await wait(frame*1000/fps-(performance.now()-start));for(const k of ['zoom','x','y'])camera[k]+=(target[k]-camera[k])*.075;
   snapshots.push({buffer:latest,camera:{...camera},actual_seconds:(performance.now()-start)/1000});
  }
  await journey;const captureElapsed=(performance.now()-start)/1000;await cdp.send('Page.stopScreencast');if(fail)throw fail;
  assert.ok(Math.abs(captureElapsed-duration)<2,'Real-time source capture drift');
  console.log(JSON.stringify({status:'SOURCE_CAPTURED',duration,actual_seconds:captureElapsed,frames:snapshots.length,last_action:actions.at(-1).seconds}));
  const file=path.join(out,'DEMO_'+duration+'_SECONDS.mp4');encoder=spawn(path.join(root,'work/story_20261014/ffmpeg.exe'),['-hide_banner','-loglevel','warning','-f','image2pipe','-vcodec','mjpeg','-framerate',String(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart','-y',file],{windowsHide:true,stdio:['pipe','ignore','pipe']});let log='';encoder.stderr.on('data',x=>log+=x);const finished=once(encoder,'close');
  const encodeStart=performance.now();let inputDims;
  for(let frame=0;frame<snapshots.length;frame++){
   const {buffer:buf,camera:cam}=snapshots[frame];inputDims=await sharp(buf).metadata();const w=inputDims.width,h=inputDims.height;
   const cw=Math.round(w/cam.zoom),ch=Math.round(h/cam.zoom),left=Math.max(0,Math.min(w-cw,Math.round(cam.x*w/1920-cw/2))),top=Math.max(0,Math.min(h-ch,Math.round(cam.y*h/1080-ch/2)));
   const image=await sharp(buf).extract({left,top,width:cw,height:ch}).resize(1920,1080).jpeg({quality:92}).toBuffer();
   if(!encoder.stdin.write(image))await once(encoder.stdin,'drain');if(frame%30===0)cameras.push({seconds:frame/fps,actual_source_seconds:snapshots[frame].actual_seconds,zoom:cam.zoom,left,top,width:cw,height:ch,source_width:w,source_height:h});
  }
  encoder.stdin.end();const [code]=await finished;if(code)throw Error(log);const encodeElapsed=(performance.now()-encodeStart)/1000;
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);const final=await state();assert.deepEqual(final.inputs,contract.inputs);assert.equal(final.assessment.height_fraction,contract.canonical_result.height_fraction);assert.equal(final.bioClass,'all');assert.ok(actions.at(-1).seconds<duration-.3,'Report/download not completed within video');
  for(const [n,h]of Object.entries(freeze.files))assert.equal(hash(await fs.readFile(path.join(out,n))),h);assert.equal(hash(await fs.readFile(path.join(app,'index.html'))),freeze.app_sha256);
  const bytes=await fs.readFile(file);await fs.writeFile(file+'.json',JSON.stringify({status:'RECORDED_PENDING_VISUAL_QA',build_id:contract.build_id,file:path.basename(file),started_utc:started,presentation_frozen_utc:freeze.frozen_utc,bytes:bytes.length,sha256:hash(bytes),duration_seconds:duration,width:1920,height:1080,fps,frames:duration*fps,source_frames:incoming,source_dimensions:inputDims,actual_capture_seconds:captureElapsed,encoding_seconds:encodeElapsed,audio:false,subtitles:false,graphic_overlays:false,method:'Real unchanged Chrome app, CDP pixels sampled continuously in real time; frozen samples are cropped/resized and encoded afterwards. No changes to interaction timing or application pixels.',focus_method:'Existing application :focus-visible styles, activated through actual keyboard focus. No simulated cursor or added highlight.',initial,final,actions,focusChecks,camera:cameras,errors,network},null,2));console.log(JSON.stringify({status:'RECORDED',duration,bytes:bytes.length,last_action:actions.at(-1).seconds,source_frames:incoming}));
 }
}finally{encoder?.stdin?.end();await b.close()}
