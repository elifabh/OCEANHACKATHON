/* Print the final human handoff and coverage matrix with the installed browser. */
import path from 'node:path';
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const require=createRequire(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json'));
const {chromium}=require('playwright');
const out=path.join(process.cwd(),'outputs/final_delivery_20261014');
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
try {
  for(const name of (process.argv.slice(2).length ? process.argv.slice(2) : ['COVERAGE_MATRIX','KULLANIM_TR'])) {
    const p=await browser.newPage();
    await p.goto(pathToFileURL(path.join(out,name+'.html')).href);
    await p.pdf({path:path.join(out,name+'.pdf'),preferCSSPageSize:true,printBackground:true});
    await p.close();
    console.log(name+'.pdf: '+(await fs.stat(path.join(out,name+'.pdf'))).size+' bytes');
  }
} finally {await browser.close()}
