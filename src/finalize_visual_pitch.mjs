import fs from 'node:fs/promises';import path from 'node:path';import {pathToFileURL} from 'node:url';
const root=process.cwd(),rt=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies'),skill='C:/Users/Elif/.codex/plugins/cache/openai-primary-runtime/presentations/26.1013.11914/skills/presentations';process.env.RUNTIME_NODE_MODULES=path.join(rt,'node/node_modules');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const work=path.join(root,'work/jury_release_20261014'),out=path.join(root,'outputs/jury_release_20261014');
for(const [variant,name,count] of [['compact','SUNDAY_3_MINUTES_FINAL',6],['extended','SUNDAY_5_MINUTES_FINAL',6],['friday','FRIDAY_INVITATION',1]]){
 const outputName=name;
 if(variant==='friday'){try{await fs.access(path.join(out,name+'.pptx'));continue;}catch{}}
 const result=await finalizePresentation({workspaceDir:root,candidatePath:path.join(work,variant+'-ready.pptx'),finalPath:path.join(out,outputName+'.pptx'),pythonExecutable:path.join(rt,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],explicitTotalSlideCount:count,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:count===6?[4]:[],materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:['Segoe UI','Georgia']},verifyArtifactToolImport:true,receiptPath:path.join(work,outputName+'.delivery.validation.json')});
 console.log(outputName,result.finalSha256);
}
