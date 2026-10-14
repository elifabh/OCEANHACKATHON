/* Capture the actual served application. Captions are added during encoding. */
import fs from 'node:fs/promises';import path from 'node:path';import {createRequire} from 'node:module';import {spawn} from 'node:child_process';import {once} from 'node:events';import crypto from 'node:crypto';
const root=process.cwd(),runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const require=createRequire(path.join(runtime,'package.json')),{chromium}=require('playwright');
const mode=process.argv[2]||'full',duration=mode==='short'?30:mode==='wave'?9:55;
const out=path.join(root,'outputs/presentations_visual_v2_20261014'),work=path.join(root,'work/visual_v2');await fs.mkdir(out,{recursive:true});await fs.mkdir(work,{recursive:true});
const d=JSON.parse(await fs.readFile(path.join(root,'outputs/map/evidence.json'),'utf8'));
const euro=n=>'EUR '+Math.round(n).toLocaleString('en-IE'),base=d.costs.default.bands;
const full=[
 [0,'Kelp forests support marine life. Coastal protection depends on local conditions.','coast'],
 [5,'One calculated West Cork pilot. Galway and Clare have different evidence roles.','places'],
 [10,'Select an assessment area on the real coastal map.','map'],
 [14,'Satellite signal, historical NPWS reference and modelled habitat stay separate.','layers'],
 [20,'14 of 17 regional reference taxa. Measured kelp decline remains unknown.','health'],
 [26,'Run with / without habitat and water-level scenarios. These are modelled effects.','wave'],
 [36,'Explore construction-funding assumptions in euros. Actual avoided damage: not quantified.','cost'],
 [40,'Change the cost fraction. This is an independent economic assumption.','change'],
 [45,'The next decision: verify species and density, then measure waves.','decision'],
 [49,'Generate and download the assessment, with a map, assumptions and research priorities.','report']
];
const short=[
 [0,'Select a West Cork assessment area. Current habitat needs field verification.','map'],
 [4,'Satellite observations, historical records and predictions stay separate.','layers'],
 [7,'14 of 17 regional taxa. Local kelp decline: unknown.','health'],
 [10,'Recalculate wave effects using local geometry and declared assumptions.','wave'],
 [16,'An adjustable euro funding comparison. Actual avoided damage: not quantified.','cost'],
 [20,'Change the scenario. Annualised capital is not annual savings.','change'],
 [23,'Plan the next field check from the evidence gaps.','decision'],
 [25,'Download a reproducible assessment and save it as PDF offline.','report']
];
const scenes=mode==='wave'?[[0,'CONCEPTUAL MODEL ILLUSTRATION / not a flood simulation','wave']]:mode==='short'?short:full;
function assTime(s){const cs=Math.round(s*100);return '0:'+String(Math.floor(cs/6000)).padStart(2,'0')+':'+String(Math.floor(cs/100)%60).padStart(2,'0')+'.'+String(cs%100).padStart(2,'0');}
const captionPath=path.join(work,'captions-'+mode+'.ass');
let ass='[Script Info]\nScriptType: v4.00+\nPlayResX: 1600\nPlayResY: 900\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Main,Segoe UI,28,&H00FFFFFF,&H00FFFFFF,&H001C302A,&H001C302A,0,0,0,0,100,100,0,0,3,14,0,2,70,70,30,1\nStyle: Credit,Segoe UI,13,&H00FFFFFF,&H00FFFFFF,&H001C302A,&H001C302A,0,0,0,0,100,100,0,0,3,3,0,7,18,18,8,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n';
ass+='Dialogue: 0,0:00:00.00,'+assTime(duration)+',Credit,,0,0,0,,REAL LOCAL APP / build '+d.build_id+' / recorded 14 Oct 2026 / OpenStreetMap, NPWS, Copernicus\n';
scenes.forEach((s,i)=>ass+='Dialogue: 1,'+assTime(s[0])+','+assTime(scenes[i+1]?.[0]??duration)+',Main,,0,0,0,,'+s[1]+'\n');await fs.writeFile(captionPath,ass);
const server=spawn(path.join(root,'.venv/Scripts/python.exe'),['src/launch_demo.py','--no-browser','--port','8860'],{windowsHide:true});let serverLog='';server.stdout.on('data',b=>serverLog+=b);server.stderr.on('data',b=>serverLog+=b);
let browser,encoder,cdp;const actions=[],errors=[];
const sleep=ms=>new Promise(r=>setTimeout(r,Math.max(0,ms)));
try{
 for(let i=0;i<100&&!serverLog.includes('Ocean Hackathon demo:');i++)await sleep(100);
 const url=serverLog.match(/http:\/\/127\.0\.0\.1:\d+\/index\.html/)?.[0];if(!url)throw new Error(serverLog);
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-background-networking']});
 const context=await browser.newContext({viewport:{width:1600,height:900},deviceScaleFactor:1,acceptDownloads:true});await context.route('https://**/*',r=>r.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(url,{waitUntil:'networkidle'});await page.waitForFunction(()=>window.ShieldStory);
 const scene=async key=>{await page.locator('[data-scene="'+key+'"]').click();await sleep(180);};
 await page.locator('#presentation-view').click();
 async function action(name){
  if(name==='coast')await scene('coast');
  if(name==='places'){await scene('places');await sleep(2500);await page.locator('#enter-cork').click();}
  if(name==='map'){await scene('map');await page.locator('#assessment-area').selectOption('1');}
  if(name==='layers'){await page.locator('[data-layer="intertidal"]').check();await sleep(mode==='short'?700:1400);await page.locator('[data-layer="historical"]').check();await page.locator('[data-layer="paths"]').check();await page.locator('#map').screenshot({path:path.join(work,'selected-evidence-map.png')});}
  if(name==='health')await scene('health');
  if(name==='wave'){await scene('wave');await page.locator('#without-kelp').click();await sleep(mode==='short'?1000:1700);await page.locator('#with-kelp').click();await sleep(1200);await page.locator('#model-water').fill('1');await page.locator('#run-assessment').click();await sleep(mode==='short'?850:1700);await page.locator('#model-water').fill('0');await page.locator('#run-assessment').click();}
  if(name==='cost'){await scene('value');await page.locator('#cc-reset').click();}
  if(name==='change'){await page.locator('#cc-effect').fill('50');await sleep(mode==='short'?1200:2600);await page.locator('#cc-reset').click();}
  if(name==='decision')await scene('decision');
  if(name==='report'){await page.locator('#generate-report').click();await page.frameLocator('#report-preview').getByLabel('Report reading size').selectOption('1.5');await sleep(mode==='short'?1200:1700);const dp=page.waitForEvent('download');await page.locator('#save-report').click();const dl=await dp;await dl.saveAs(path.join(out,'ASSESSMENT_GROUP_1.html'));await sleep(800);await page.locator('#report-preview').evaluate(e=>e.contentWindow.scrollTo({top:870,behavior:'smooth'}));}
  actions.push({completed:name,assessment:await page.evaluate(()=>{const r=ShieldAssessment.getResult();return r?{group:r.group,height:r.height_fraction,energy:r.energy_fraction,length_m:r.comparison_length_m,low_capital:r.bands.low.capital_eur,high_capital:r.bands.high.capital_eur,inputs:r.inputs}:null;})});
 }
 await action(mode==='short'?'map':'coast');await sleep(600);
 await page.screenshot({path:path.join(work,'demo_'+mode+'_initial.png')});
 cdp=await context.newCDPSession(page);let latest=await page.screenshot({type:'jpeg',quality:90});
 cdp.on('Page.screencastFrame',event=>{latest=Buffer.from(event.data,'base64');void cdp.send('Page.screencastFrameAck',{sessionId:event.sessionId});});
 await cdp.send('Page.startScreencast',{format:'jpeg',quality:90,maxWidth:1600,maxHeight:900,everyNthFrame:1});
 const file=path.join(out,mode==='wave'?'conceptual_wave.mp4':mode==='short'?'DEMO_30_SECONDS.mp4':'DEMO_55_SECONDS.mp4');
 const filter='ass=work/visual_v2/captions-'+mode+'.ass';
 encoder=spawn(path.join(root,'work/story_20261014/ffmpeg.exe'),['-hide_banner','-loglevel','warning','-f','image2pipe','-vcodec','mjpeg','-framerate','20','-i','pipe:0','-vf',filter,'-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart','-y',file],{cwd:root,windowsHide:true,stdio:['pipe','ignore','pipe']});let encLog='';encoder.stderr.on('data',b=>encLog+=b);const ended=once(encoder,'close');
 const start=performance.now();
 const runActions=(async()=>{for(const [at,caption,name] of scenes){await sleep(at*1000-(performance.now()-start));actions.push({scheduled_seconds:at,actual_seconds:(performance.now()-start)/1000,name,caption});await action(name);}})();
 for(let frame=0;frame<duration*20;frame++){await sleep(frame*50-(performance.now()-start));if(!encoder.stdin.write(latest))await once(encoder.stdin,'drain');}
 encoder.stdin.end();await runActions;const [code]=await ended;if(code!==0)throw new Error(encLog);
 await cdp.send('Page.stopScreencast');const reportPage=await context.newPage();await reportPage.goto('file:///'+path.join(out,'ASSESSMENT_GROUP_1.html').replaceAll('\\','/'));await reportPage.pdf({path:path.join(out,'ASSESSMENT_GROUP_1.pdf'),printBackground:true,preferCSSPageSize:true});await reportPage.close();if(errors.length)throw new Error(errors.join('\n'));
 const bytes=await fs.readFile(file);const manifest={file:path.basename(file),sha256:crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,build_id:d.build_id,duration_seconds:duration,frames:duration*20,fps:20,audio:'None; deliberate silent screen recording with burned-in English captions',method:'Chrome DevTools Page.startScreencast of the real localhost application, sampled in real time and encoded as H.264. No UI values or evidence replaced for recording.',actions,uncaught_errors:errors};
 await fs.writeFile(path.join(out,path.basename(file)+'.json'),JSON.stringify(manifest,null,2));console.log(JSON.stringify({file:manifest.file,duration:duration,build:d.build_id,bytes:bytes.length,errors}));
}finally{if(encoder&&!encoder.killed)encoder.stdin?.end();if(browser)await browser.close();server.kill();}
