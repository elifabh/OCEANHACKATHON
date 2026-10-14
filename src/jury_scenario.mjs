import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
export async function presentationScenario(root=process.cwd()) {
 const d=JSON.parse(await fs.readFile(path.join(root,'outputs/map/evidence.json'),'utf8'));
 const scenario=JSON.parse(await fs.readFile(path.join(root,'src/presentation_scenario.json'),'utf8'));
 assert.deepEqual(d.presentation_scenario,scenario,'Rebuild the app before generating presentation material');
 const require=createRequire(import.meta.url);require(path.join(root,'src/parametric.js'));
 const scope=d.parametric.scopes[String(scenario.group)];
 const calculator=globalThis.ParametricCoast||globalThis.window?.ParametricCoast;
 const r=calculator.calculate(scope,scope.directions[String(scenario.direction_offset_deg)],d.costs.rates,scenario.inputs);
 return {d,scenario,scope,r};
}
