import fs from 'node:fs/promises';import path from 'node:path';import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';import assert from 'node:assert/strict';
const root=process.cwd(),out=path.join(root,'outputs/final_creative_20261015'),req=createRequire(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json')),{chromium}=req('playwright');
const b=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--autoplay-policy=no-user-gesture-required']});
try{
 const films=await Promise.all([75,30].map(async n=>{
  const html=path.join(out,'qa','play-'+n+'.html');await fs.writeFile(html,'<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#000}video{width:100vw;height:100vh}</style><video controls muted playsinline src="../DEMO_'+n+'_SECONDS.mp4"></video>');
  const p=await b.newPage({viewport:{width:1920,height:1080}});await p.goto(pathToFileURL(html).href);await p.locator('video').evaluate(async v=>{await v.play()});await p.waitForFunction(()=>document.querySelector('video').ended,{},{timeout:(n+20)*1000});
  const r=await p.locator('video').evaluate(v=>({ended:v.ended,current_time:v.currentTime,duration:v.duration,width:v.videoWidth,height:v.videoHeight,audio_tracks:v.audioTracks?.length??(v.webkitAudioDecodedByteCount>0?1:0),playback_quality:v.getVideoPlaybackQuality().toJSON?.()??{total:v.getVideoPlaybackQuality().totalVideoFrames,dropped:v.getVideoPlaybackQuality().droppedVideoFrames}}));assert.ok(r.ended);assert.ok(Math.abs(r.duration-n)<.1);await p.close();return{expected_duration:n,...r};
 }));
 await fs.writeFile(path.join(out,'qa/media-playback.json'),JSON.stringify({status:'PASS',films},null,2));console.log(JSON.stringify(films));
}finally{await b.close()}
