/* Capture the actual served application. Captions are added during encoding. */
import fs from 'node:fs/promises';import path from 'node:path';import {createRequire} from 'node:module';import {spawn} from 'node:child_process';import {once} from 'node:events';import crypto from 'node:crypto';
const root=process.cwd(),runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const require=createRequire(path.join(runtime,'package.json')),{chromium}=require('playwright');
const mode=process.argv[2]||'full',duration=mode==='short'?30:mode==='wave'?9:55;
const out=path.join(root,'outputs/presentations_final_20261014'),work=path.join(root,'work/story_20261014');await fs.mkdir(out,{recursive:true});
const d=JSON.parse(await fs.readFile(path.join(root,'outputs/map/evidence.json'),'utf8'));
const euro=n=>'EUR '+Math.round(n).toLocaleString('en-IE'),base=d.costs.default.bands;
const full=[
 [0,'Select a West Cork model area. Present kelp remains unvalidated.','map'],
 [5,'Reveal satellite intertidal signals, then historical NPWS surveys.','layers'],
 [12,'Regional conditions and '+d.biodiversity.present+' of '+d.biodiversity.total+' reference taxa. Measured bed loss is unknown.','health'],
 [20,'With / without assumed kelp. Model illustration, not a flood simulation.','wave'],
 [27,'Engineering funding comparison: '+euro(base.low.pro_rata_cost_scenario_eur)+'–'+euro(base.high.pro_rata_cost_scenario_eur)+' capital.','cost'],
 [34,'Change an assumption. Actual avoided damage stays NOT QUANTIFIED.','change'],
 [40,'Survey priority: resolve historical evidence and validate habitat first.','decision'],
 [46,'Mizen transfer: '+d.transfer.assessed_cells+' assessed, '+d.transfer.above_threshold+' above threshold. No estimate, not kelp absence.','transfer'],
 [51,'Practical result: a traceable brief for the next field decision.','finish']
];
const short=[
 [0,'West Cork: modelled habitat. Current species and density unvalidated.','map'],
 [3,'Satellite proxy and historical survey are different evidence.','layers'],
 [7,d.biodiversity.present+' of '+d.biodiversity.total+' regional reference taxa. Measured kelp loss: unknown.','health'],
 [11,'Conditional waves: '+(d.physical.height_fraction*100).toFixed(2)+'% height / '+(d.physical.energy_fraction*100).toFixed(2)+'% energy.','wave'],
 [16,'Adjustable capital scenario. Actual avoided damage: NOT QUANTIFIED.','cost'],
 [20,'The user-assumed cost fraction is not a measured saving.','change'],
 [23,'Survey first: low confidence, historical reference conflicts.','decision'],
 [27,'Transfer needs local evidence. Mizen returns no estimate.','transfer']
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
 const context=await browser.newContext({viewport:{width:1600,height:900},deviceScaleFactor:1});await context.route('https://**/*',r=>r.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(url,{waitUntil:'networkidle'});await page.waitForFunction(()=>window.ShieldStory);
 const show=async selector=>page.locator(selector).evaluate(e=>scrollTo({top:scrollY+e.getBoundingClientRect().top-88,behavior:'instant'}));
 async function action(name){
  if(name==='map'){await page.locator('[data-group=\"1\"]').evaluate(e=>e.closest('details').open=true);await page.locator('[data-group="1"]').click();await show('.map-toolbar');}
  if(name==='layers'){await page.locator('#focus-cork').click();await page.locator('[data-layer="historical"]').uncheck();await show('.map-toolbar');await sleep(mode==='short'?1100:2200);await page.locator('[data-layer="historical"]').check();await show('.map-toolbar');}
  if(name==='health'){await show('.living-section .two-columns');await sleep(mode==='short'?1200:3000);await show('.biodiversity-layout');}
  if(name==='wave'){await show('.physical-layout');await page.locator('#without-kelp').click();await show('.physical-layout');await sleep(mode==='short'?1100:2200);await page.locator('#with-kelp').click();await show('.physical-layout');}
  if(name==='cost'){await page.locator('#cc-reset').click();await show('.cost-boundary');}
  if(name==='change'){await page.locator('#cc-width').fill('150');await show('.cost-boundary');await sleep(mode==='short'?900:2200);await page.locator('#cc-reset').click();await show('.cost-boundary');}
  if(name==='decision'){await show('#decision-brief');await sleep(mode==='short'?1100:2400);await show('.restoration-layout');}
  if(name==='transfer'){await page.locator('#transfer-run').click();await show('#transfer');}
  if(name==='finish')await show('#decision-brief');
 }
 await action(mode==='wave'?'wave':'map');await sleep(600);
 await page.screenshot({path:path.join(out,mode==='wave'?'wave_poster.png':'demo_'+mode+'_poster.png')});
 cdp=await context.newCDPSession(page);let latest=await page.screenshot({type:'jpeg',quality:90});
 cdp.on('Page.screencastFrame',event=>{latest=Buffer.from(event.data,'base64');void cdp.send('Page.screencastFrameAck',{sessionId:event.sessionId});});
 await cdp.send('Page.startScreencast',{format:'jpeg',quality:90,maxWidth:1600,maxHeight:900,everyNthFrame:1});
 const file=path.join(out,mode==='wave'?'conceptual_wave.mp4':mode==='short'?'DEMO_30_SECONDS.mp4':'DEMO_55_SECONDS.mp4');
 const filter='ass=work/story_20261014/captions-'+mode+'.ass';
 encoder=spawn(path.join(work,'ffmpeg.exe'),['-hide_banner','-loglevel','warning','-f','image2pipe','-vcodec','mjpeg','-framerate','20','-i','pipe:0','-vf',filter,'-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart','-y',file],{cwd:root,windowsHide:true,stdio:['pipe','ignore','pipe']});let encLog='';encoder.stderr.on('data',b=>encLog+=b);const ended=once(encoder,'close');
 const start=performance.now();
 const runActions=(async()=>{for(const [at,caption,name] of scenes){await sleep(at*1000-(performance.now()-start));actions.push({scheduled_seconds:at,actual_seconds:(performance.now()-start)/1000,name,caption});await action(name);}})();
 for(let frame=0;frame<duration*20;frame++){await sleep(frame*50-(performance.now()-start));if(!encoder.stdin.write(latest))await once(encoder.stdin,'drain');}
 encoder.stdin.end();await runActions;const [code]=await ended;if(code!==0)throw new Error(encLog);
 await cdp.send('Page.stopScreencast');if(errors.length)throw new Error(errors.join('\n'));
 const bytes=await fs.readFile(file);const manifest={file:path.basename(file),sha256:crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,build_id:d.build_id,duration_seconds:duration,frames:duration*20,fps:20,audio:'None; deliberate silent screen recording with burned-in English captions',method:'Chrome DevTools Page.startScreencast of the real localhost application, sampled in real time and encoded as H.264. No UI values or evidence replaced for recording.',actions,uncaught_errors:errors};
 await fs.writeFile(path.join(out,path.basename(file)+'.json'),JSON.stringify(manifest,null,2));console.log(JSON.stringify(manifest,null,2));
}finally{if(encoder&&!encoder.killed)encoder.stdin?.end();if(browser)await browser.close();server.kill();}

