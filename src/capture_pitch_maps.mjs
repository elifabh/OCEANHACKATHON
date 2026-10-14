import fs from 'node:fs/promises';import path from 'node:path';import {createRequire} from 'node:module';import {spawn} from 'node:child_process';
const root=process.cwd(),runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),require=createRequire(path.join(runtime,'package.json')),{chromium}=require('playwright'),sharp=require('sharp');
const work=path.join(root,'work/story_20261014'),out=path.join(root,'outputs/final_20261014/qa');
// Rasterise an original map from Natural Earth coordinates, not documentary imagery.
await sharp(path.join(work,'ireland.svg')).resize(780,930).png().toFile(path.join(work,'ireland.png'));
const server=spawn(path.join(root,'.venv/Scripts/python.exe'),['src/launch_demo.py','--no-browser','--port','8865'],{windowsHide:true});let log='';server.stdout.on('data',b=>log+=b);server.stderr.on('data',b=>log+=b);let browser;
try{for(let i=0;i<100&&!log.includes('Ocean Hackathon demo:');i++)await new Promise(r=>setTimeout(r,100));const url=log.match(/http:\/\/127\.0\.0\.1:\d+\/index\.html/)?.[0];if(!url)throw new Error(log);browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});const context=await browser.newContext({viewport:{width:1600,height:1000},reducedMotion:'reduce'});await context.route('https://**/*',r=>r.abort());const page=await context.newPage();await page.goto(url,{waitUntil:'networkidle'});await page.waitForFunction(()=>window.ShieldStory);
await page.locator('#focus-pilot').click();await page.waitForTimeout(900);
await page.locator('[data-layer="model"]').uncheck();await page.locator('[data-layer="intertidal"]').check();await page.waitForTimeout(900);await page.locator('#map').screenshot({path:path.join(out,'pitch_satellite.png')});
await page.locator('[data-layer="model"]').check();await page.waitForTimeout(900);await page.locator('#map').screenshot({path:path.join(out,'pitch_model.png')});
await page.locator('[data-layer="historical"]').check();await page.waitForTimeout(900);await page.locator('#map').screenshot({path:path.join(out,'pitch_historical.png')});
await page.locator('#focus-cork').click();await page.waitForTimeout(1100);await page.locator('#map').screenshot({path:path.join(out,'pitch_cork_context.png')});
await page.locator('#without-kelp').click();await page.waitForTimeout(300);await page.locator('#wave-diagram').screenshot({path:path.join(out,'wave_without.png')});
console.log('Actual map states captured after settling; original SVG context rasterised.');
}finally{if(browser)await browser.close();server.kill();}
