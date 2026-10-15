/* Source-derived atlas motion and explicitly conceptual scientific animations.
   Does not modify app, research data or calculation engine. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
const root=process.cwd(),out=path.join(root,'outputs/final_creative_20261015'),assets=path.join(out,'assets'),work=path.join(root,'work/creative_20261015');
const req=createRequire(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json'));
const {chromium}=req('playwright'),sharp=req('sharp');
const d=JSON.parse(await fs.readFile('outputs/final_overnight_20261015/app/evidence.json','utf8'));
const old=JSON.parse(await fs.readFile('outputs/final_overnight_20261015/presentation_contract.json','utf8'));
const c=d.product.cases.cape_clear;
const source={build_id:d.build_id,result:old.canonical_result,ireland:JSON.parse(await fs.readFile('src/assets/story/ireland-context.geojson','utf8')),land:c.land,history:c.historical,assets:c.assets,cell:c.scenario_layer,paths:c.scenario.directions['210'].geometry,records:c.case.nearby_dated_observations,origin:c.case.habitat_scenario_origin_lonlat};
await fs.writeFile(path.join(assets,'animation-source.json'),JSON.stringify(source));
const images={};
for(const name of ['fish','shell','crab','satellite','wave','thermometer','microscope','python','geopandas']){
 const p=path.join(assets,name+'.svg');const b=await fs.readFile(p);images[name]='data:image/svg+xml;base64,'+b.toString('base64');
 await sharp(b).resize({width:name==='python'||name==='geopandas'?600:240}).png().toFile(path.join(assets,name+'.png'));
}
images.kelp='data:image/jpeg;base64,'+(await fs.readFile('src/assets/story/kelp-forest.jpg')).toString('base64');
images.coast='data:image/jpeg;base64,'+(await fs.readFile('src/assets/story/roaringwater-bay.jpg')).toString('base64');
const scene=await fs.readFile('src/creative_animation_scene.js','utf8');
const html='<!doctype html><meta charset="utf-8"><style>*{margin:0}body{background:#082B3B}canvas{display:block}</style><canvas width="1280" height="520"></canvas><script>const SOURCE='+JSON.stringify(source)+';const IMAGE_URLS='+JSON.stringify(images)+';</script><script>'+scene+'</script>';
await fs.writeFile(path.join(work,'animations.html'),html);
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const page=await browser.newPage({viewport:{width:1280,height:520}});await page.goto(pathToFileURL(path.join(work,'animations.html')).href);await page.waitForFunction(()=>window.ready);
const plans=[{name:'comparison',duration:28},{name:'atlas',duration:28},{name:'mechanism',duration:26},{name:'ecology',duration:22},{name:'monitoring',duration:26}];
const selected=process.argv[2];
const ffmpeg=path.join(root,'work/story_20261014/ffmpeg.exe');
async function command(args){const p=spawn(ffmpeg,args,{windowsHide:true,stdio:['ignore','ignore','pipe']});let log='';p.stderr.on('data',x=>log+=x);const [code]=await once(p,'close');if(code)throw Error(log);}
try{
 if(selected==='preview')for(const plan of plans)for(const t of [0,5,10,15,20,plan.duration-1]){await page.evaluate(({name,t})=>render(name,t),{name:plan.name,t});await page.screenshot({path:path.join(assets,plan.name+'-'+String(t).padStart(2,'0')+'.png')});}
 for(const plan of plans.filter(x=>!selected||selected===x.name)){
  const movie=path.join(assets,plan.name+'.mp4'),fps=24;
  const encoder=spawn(ffmpeg,['-hide_banner','-loglevel','error','-f','image2pipe','-vcodec','png','-framerate',String(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart','-y',movie],{windowsHide:true,stdio:['pipe','ignore','pipe']});let log='';encoder.stderr.on('data',x=>log+=x);const ended=once(encoder,'close');
  for(let frame=0;frame<plan.duration*fps;frame++){
   const png=await page.evaluate(({name,t})=>{render(name,t);return document.querySelector('canvas').toDataURL('image/png').split(',')[1]},{name:plan.name,t:frame/fps});
   if(!encoder.stdin.write(Buffer.from(png,'base64')))await once(encoder.stdin,'drain');
   if(frame%(fps*5)===0)console.log(plan.name,frame/fps+'s rendered');
  }
  encoder.stdin.end();const [code]=await ended;if(code)throw Error(log);
  for(const t of [0,5,10,15,20,plan.duration-1]){
   await page.evaluate(({name,t})=>render(name,t),{name:plan.name,t});await page.screenshot({path:path.join(assets,plan.name+'-'+String(t).padStart(2,'0')+'.png')});
  }
  await command(['-hide_banner','-loglevel','error','-i',movie,'-vf','fps=12,scale=1280:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=192:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3','-loop','-1','-y',path.join(assets,plan.name+'.gif')]);
  await fs.writeFile(path.join(assets,plan.name+'.json'),JSON.stringify({...plan,build_id:d.build_id,width:1280,height:520,fps,gif_fps:12,gif_loops:1,scientific_boundary:plan.name==='comparison'?'Conceptual integration of existing evidence categories; historical, observed, modelled and assumed meanings remain distinct. No new habitat map or independent ecological validation.':plan.name==='atlas'?'Existing source geometries; scale-dependent atlas orientation; historical and assumed evidence kept distinct.':plan.name==='mechanism'?'Conceptual geometry; normalized wave-height ratio from unchanged deterministic engine; no shoreline simulation.':plan.name==='monitoring'?'Proposed repeat-survey design; illustrative nonlocal photograph crops; no observed temporal change or restoration result.':'Conceptual habitat relationships, not Cape Clear footage, abundance or restoration prediction.',source:'src/creative_animation_scene.js',numeric_result:plan.name==='mechanism'?old.canonical_result:null},null,2));
  console.log('FINISHED',plan.name);
 }
}finally{await browser.close();}
