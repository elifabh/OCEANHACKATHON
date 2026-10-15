// Fixed local tool: caller supplies state, never code or file paths.
const fs=require('node:fs'),path=require('node:path');
require('./parametric.js');require('./assessment_assistant.js');
const root=path.resolve(__dirname,'..'),data=JSON.parse(fs.readFileSync(path.join(root,'outputs/final_overnight_20261015/app/evidence.json'),'utf8'));
let input='';process.stdin.on('data',c=>{input+=c;if(input.length>1000000)process.exit(2);});process.stdin.on('end',()=>{try{const q=JSON.parse(input);process.stdout.write(JSON.stringify(AssessmentAssistant.answer(data,q.state,q.question,q.model_choice)));}catch(e){process.stderr.write(e.message);process.exitCode=2;}});
