import fs from 'node:fs/promises';import path from 'node:path';import {createRequire} from 'node:module';
const root=process.cwd(),require=createRequire(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json')),sharp=require('sharp');
const out=path.join(root,'outputs/presentations_visual_v2_20261014/previews');await fs.mkdir(out,{recursive:true});
const old=path.join(root,'outputs/final_20261014/qa/powerpoint/SUNDAY_3_MINUTES_FINAL'),work=path.join(root,'work/visual_v2');
const text=(s,w,h,size=28)=>({input:Buffer.from(`<svg width="${w}" height="${h}"><text x="18" y="${size+8}" fill="#12313a" font-family="Segoe UI" font-size="${size}">${s}</text></svg>`)});
let beforeAfter=[],after=[];
beforeAfter.push({...text('BEFORE / 14 OCTOBER',960,56),left:0,top:0},{...text('REVISED / ACTUAL FILM FRAME ON SCENE 5',960,56,25),left:960,top:0});
for(let i=1;i<=6;i++){
 const prev=await sharp(path.join(old,`slide-${i}.png`)).resize(944,531).png().toBuffer();
 const nextFile=i===5?path.join(work,'film-euro.png'):path.join(work,'render-compact',`slide-${i}.png`);
 const next=await sharp(nextFile).resize(944,531).png().toBuffer();
 beforeAfter.push({input:prev,left:8,top:56+(i-1)*547},{input:next,left:968,top:56+(i-1)*547});
 after.push({input:await sharp(nextFile).resize(624,351).png().toBuffer(),left:8+((i-1)%3)*640,top:48+Math.floor((i-1)/3)*367});
}
await sharp({create:{width:1920,height:3340,channels:3,background:'#f5f3e9'}}).composite(beforeAfter).png().toFile(path.join(out,'BEFORE_AFTER_SIX_SCENES.png'));
await sharp({create:{width:1920,height:790,channels:3,background:'#f5f3e9'}}).composite([{...text('REVISED JURY STORY / scene 5 shows a representative real video frame',1920,48,25),left:0,top:0},...after]).png().toFile(path.join(out,'REVISED_SIX_SCENES.png'));
const ui=['coast','map','value','report'],tiles=[];
for(let i=0;i<ui.length;i++){const f=path.join(root,'outputs/visual_v2_20261014/qa','ui-'+ui[i]+'.png');await fs.copyFile(f,path.join(out,'UI_'+ui[i].toUpperCase()+'.png'));tiles.push({input:await sharp(f).resize(944,531,{fit:'contain',background:'#f5f3e9'}).png().toBuffer(),left:8+(i%2)*960,top:48+Math.floor(i/2)*547});}
await sharp({create:{width:1920,height:1145,channels:3,background:'#f5f3e9'}}).composite([{...text('ACTUAL APPLICATION / coast, selected map, conditional economics, report',1920,48,25),left:0,top:0},...tiles]).png().toFile(path.join(out,'NEW_UI_FOUR_VIEWS.png'));
console.log('Before/after six-scene contact sheet and four real UI screenshots saved');
