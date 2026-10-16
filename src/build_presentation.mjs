/* Local, editable jury deck. Reads the same evidence as the application. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const root=path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1')),'..');
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const require=createRequire(path.join(runtime,'node/node_modules/package.json'));
const {Presentation,PresentationFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const skill='C:/Users/Elif/.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations';
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const work=path.join(root,'work/presentation');
const out=path.join(root,'outputs/presentations_20261013');
await fs.mkdir(work,{recursive:true});await fs.mkdir(out,{recursive:true});
const d=JSON.parse(await fs.readFile(path.join(root,'outputs/map/evidence.json'),'utf8'));
const p=Presentation.create({slideSize:{width:1280,height:720}});
const C={paper:'#F5F4EE',ink:'#15333A',green:'#176655',muted:'#596B6C',purple:'#8364A0',blue:'#346F94',amber:'#AD712C',line:'#CDD5CF'};
const pct=x=>(x*100).toFixed(1)+'%';
const eur=x=>'€'+Math.round(x).toLocaleString('en-IE');
const FONT='Segoe UI',SERIF='Georgia';
function text(s,t,x,y,w,h,size=26,color=C.ink,font=FONT,bold=false){
 const q=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 q.text=t;q.text.style={typeface:font,fontSize:size,color,bold};return q;
}
function slide(title,number){const s=p.slides.add();s.background.fill=C.paper;text(s,title,64,50,1152,90,46,C.ink,SERIF);text(s,'Ocean Hackathon Cork 2026   /   '+number,64,665,900,28,16,C.muted);return s;}
function note(s,n,sources){s.speakerNotes.text=n+'\n\nPreparation snapshot: 13 October 2026. Do not present pre-event work as event team achievement.\nSources:\n'+sources.join('\n');}
async function image(s,file,x,y,w,h,alt){const b=await fs.readFile(file);s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',fit:'contain',position:{left:x,top:y,width:w,height:h},alt});}
const notes=[];
// 1. Cover. Real imagery with source caption.
{
 const s=p.slides.add();s.background.fill=C.paper;
 text(s,'Seeing the\nInvisible Shield',64,95,660,190,70,C.ink,SERIF);
 text(s,'Valuing Coastal Habitats\nas Natural Infrastructure',68,307,635,105,31);
 text(s,'West Cork working prototype\nElif Gul Abdul Halim\nChallenge ORK02',68,480,610,100,23,C.muted);
 await image(s,path.join(root,'outputs/map/sentinel-context.png'),760,95,455,455,'Sentinel-2 water-stretched RGB coastal context. Land is masked grey.');
 text(s,'Modified Copernicus Sentinel data, 14 July 2022\nWater-stretched RGB. Grey areas mask land.',770,557,445,55,16,C.muted);
 text(s,'AI-assisted preparation, 13 October 2026. Event work will be recorded separately.',68,657,1140,30,16,C.muted);
 const n='Our challenge asks how coastal habitats can enter decisions about natural infrastructure. This prototype focuses on Sherkin Island and Roaringwater Bay in West Cork. It connects habitat evidence to a transparent physical illustration and a conditional cost comparison. The practical question is which observations would support a credible claim of protection. This is preparation completed before the event, with AI assistance. We will identify work contributed during the hackathon separately.';
 notes.push(n);note(s,n,['Published challenge: https://www.campusmer.fr/all-challenges-ork02-seeing-the-invisible-shield-valuing-coastal-habitats-as-natural-infrastructure-4385-475-0-0.html','Imagery: outputs/thumbnails/sherkin_baltimore__2022-07-14__T29UMT.png; Copernicus Sentinel terms https://dataspace.copernicus.eu/terms-and-conditions']);
}
// 2. Map and evidence taxonomy.
{
 const s=slide('Habitat evidence around Sherkin',2);
 await image(s,path.join(root,'outputs/overnight_20261013/qa/map_evidence_context.png'),64,159,730,439,'Local OSM coastline with modelled habitat, satellite intertidal proxy and historical NPWS reference.');
 text(s,'DETECTED SIGNAL',834,166,380,30,19,C.blue,FONT,true);
 text(s,d.intertidal.area_ha.toFixed(1)+' ha intertidal proxy\nSeven Sentinel-2 scenes, 2022\nSpecies unvalidated',834,207,380,115,24);
 text(s,'MODELLED HABITAT',834,343,380,30,19,C.green,FONT,true);
 text(s,'1.75 ha in seven cells\nThree disconnected groups\nCurrent kelp unconfirmed',834,384,380,110,24);
 text(s,'HISTORICAL REFERENCE',834,512,390,30,19,C.purple,FONT,true);
 text(s,'NPWS Laminaria communities\n2011 survey synthesis',834,553,380,72,24);
 text(s,'© OpenStreetMap contributors (ODbL), NPWS and Copernicus. Colours identify evidence classes.',70,608,700,38,15,C.muted);
 const n='The map deliberately carries three evidence classes. Blue is a detected intertidal macroalgae proxy from seven satellite scenes. It does not identify subtidal Laminaria hyperborea. Green represents seven retained model cells, covering one point seven five hectares in three separate groups. Purple is historical NPWS community mapping. That reference draws on older surveys, although the distribution package dates from 2025. Clicking a group reveals its physical illustration, regional context and confidence. The pilot remains here because the evidence sources overlap, not because it produces a positive euro result.';
 notes.push(n);note(s,n,['Evidence build '+d.build_id,'NPWS https://www.npws.ie/maps-and-data/designated-site-data/ssco-data','Source geometry CRS EPSG:29903 transformed to EPSG:2157; web EPSG:4326','OSM https://www.openstreetmap.org/copyright','Sentinel: application evidence.json intertidal']);
}
// 3. Required native chart: modelled transmission.
{
 const s=slide('A conditional physical effect inside habitat',3);
 const c=s.charts.add('bar',{position:{left:64,top:190,width:728,height:376},categories:['Without assumed kelp','With assumed kelp'],series:[{name:'Relative outgoing wave height',values:[1,1-d.physical.height_fraction],fill:C.green}],barOptions:{direction:'column',grouping:'clustered',gapWidth:110},hasLegend:false,chartFill:C.paper,plotAreaFill:C.paper,xAxis:{textStyle:{fontSize:21,fill:C.ink}},yAxis:{visible:true,min:0,max:1.1,majorUnit:.25,numberFormatCode:'0%',textStyle:{fontSize:20,fill:C.muted},majorGridlines:{fill:C.line,width:.5}},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.0%',textStyle:{fontSize:23,fill:C.ink}}});
 applyPresentationChartFont(c,{fontFamily:FONT});
 text(s,pct(d.physical.height_fraction),854,190,355,91,76,C.green,SERIF);
 text(s,'height reduction',862,287,350,40,25);
 text(s,pct(d.physical.energy_fraction)+' energy reduction',854,366,355,66,31,C.ink,SERIF);
 text(s,'At LAT, across assumed cells\nUniform incident energy\nLaboratory-based coefficients',857,451,355,130,23,C.muted);
 text(s,'No transformed shoreline hazard or measured reduction in damage. Tide and direction alter the model domain.',68,592,1145,54,23,C.muted);
 const n='The physical calculation traces actual paths through the model polygons. It excludes the gaps between groups and checks land barriers. At the baseline LAT depth, the illustration gives about five point eight percent reduction in wave height and eleven point one percent in energy. These are different quantities. The coefficients come from a laboratory kelp study, with a four to ten metre depth domain and assumed plant properties. The offshore wave bearing is a scenario input. We have not transformed it into a validated nearshore incident spectrum. Raising water levels takes some paths outside the experimental depth range, so those results become unknown.';
 notes.push(n);note(s,n,['Dubi & Tørum (1996), https://doi.org/10.1061/9780784402429.203','INFOMAR https://infomar.ie/data','CMEMS IBI wave reanalysis, 2015–2024, nearest wet point '+(d.wave.distance_to_model_centroid_m/1000).toFixed(2)+' km offshore','src/coastal_physics.py; actual polygon chord integration, <=5 m ray quadrature','Height '+d.physical.height_fraction+'; energy '+d.physical.energy_fraction+'; these are width-weighted conditional means, not confidence intervals']);
}
// 4. Editable monetary evidence table, not a total ecosystem benefit.
{
 const s=slide('Conditional engineering cost comparison',4);
 const b=d.costs.default.bands;
 text(s,eur(b.low.pro_rata_cost_scenario_eur)+'–'+eur(b.high.pro_rata_cost_scenario_eur),65,157,1150,90,59,C.green,SERIF);
 text(s,'Illustrative one-off capital scenario',68,252,1100,50,28);
 const vals=[['Assumption','Default scenario'],['Model area / assumed width','17,500 m² / 100 m = 175 m'],['Project pro-rata share','15.2%, preserved original assumption'],['Annualisation','4% discount rate, 50 years'],['Annualised capital equivalent',eur(b.low.annualised_pro_rata_scenario_eur_per_year)+'–'+eur(b.high.annualised_pro_rata_scenario_eur_per_year)+' / year']];
 const t=s.tables.add({rows:5,columns:2,left:67,top:334,width:1130,height:245,columnWidths:[465,665],values:vals});
 t.borders.assign({fill:C.line,width:.6});
 for(let r=0;r<5;r++)for(let c=0;c<2;c++){const cell=t.getCell(r,c);cell.fill=r===0?C.green:C.paper;cell.text.style={typeface:FONT,fontSize:23,color:r===0?'#FFFFFF':C.ink,bold:r===0};}
 text(s,'Actual avoided damage: not quantified. Service equivalence, least cost and demand remain unproven.',68,600,1140,55,24,C.muted);
 const n='The euro result answers a carefully limited question. What capital amount follows if we take selected approved engineering funding from one Wexford site, assume a comparison length, and apply a chosen cost share? With the preserved original assumptions, the range is about one hundred and fifteen to one hundred and ninety thousand euros. Annualisation gives about five thousand three hundred to eight thousand nine hundred euros per year. This is an accounting equivalent of capital, not annual savings. The pro-rata relationship is our sensitivity assumption. Revetment funding is an imperfect comparator, and the three replacement-cost conditions remain unproven. The calculator lets the jury change every assumption and export it.';
 notes.push(n);note(s,n,['OPW public funding records https://www.floodinfo.ie/county-summary/?c=25','2024: €668,921 /155m and €657,338 /100m; 2026: €500,535 /70m. One site, nominal approved grants, not final costs.','Formula L=A/W, C=L*funding_rate*share, annual=C*r/(1-(1+r)^(-n)).','The retained 15.2% cost-share default comes from a historical model baseline. The new 11.1% energy result is a separate optional sensitivity, never an empirically validated saving.','No OPW flood-map geometry is used.']);
}
// 5. Native regional temperature chart and presence indicator.
{
 const s=slide('Condition needs repeated observation',5);
 const c=s.charts.add('line',{position:{left:64,top:215,width:745,height:334},categories:d.sst.annual.map(r=>String(r.year)),lineOptions:{smooth:false},series:[{name:'Sampled SST, °C',smooth:false,values:d.sst.annual.map(r=>r.mean_c),line:{fill:C.blue,width:3},marker:{symbol:'circle',size:6,fill:C.blue}}],hasLegend:false,chartFill:C.paper,plotAreaFill:C.paper,xAxis:{textStyle:{fontSize:17,fill:C.muted}},yAxis:{min:10,max:15,numberFormatCode:'0.0',title:{text:'SST, °C',textStyle:{fontSize:20,fill:C.ink}},textStyle:{fontSize:19,fill:C.muted},majorGridlines:{fill:C.line,width:.5}}});
 applyPresentationChartFont(c,{fontFamily:FONT});
 text(s,'NOAA OISST regional context, 2015–2024',68,164,770,42,26);
 text(s,'Every 30th day. Annual sample averages.\nSurface context, about '+(d.sst.distance_to_bed_m/1000).toFixed(1)+' km from the pilot.',68,553,745,68,21,C.muted);
 text(s,'14 of 17',861,209,370,89,62,C.green,SERIF);
 text(s,'reference taxa recorded\nin West Cork',867,306,335,86,28);
 text(s,'Regional presence, biased\nby observation effort.\nUnrecorded is not absent.',867,424,335,117,23,C.muted);
 text(s,'Measured kelp decline: unknown',861,566,351,76,28,C.ink,SERIF);
 const n='Condition needs a different evidence chain. Offshore waves and regional surface temperatures describe the environment. The temperature chart uses a small NOAA subset, sampling every thirtieth day. The annual sample averages are not full annual climatological means or a marine heatwave diagnosis. Neither this chart nor EPA water-quality status establishes kelp loss. We need comparable repeat habitat surveys. The biodiversity indicator records fourteen of seventeen reference taxa across West Cork records. It counts presence, with substantial differences in sampling effort. It does not claim eighty-two percent biodiversity, and it is not a survey of these seven cells.';
 notes.push(n);note(s,n,['NOAA OISST v2.1 https://doi.org/10.25921/RE9P-PT57 ; subset URL and SHA256 in outputs/overnight_20261013/inputs/oisst_snapshots.csv.meta.json','Regional mean sample count '+d.sst.n_days+'; source sampling every 30th daily time step','Schoenrock et al. (2020) https://doi.org/10.1002/ece3.6345 ; source occurrence aggregation, outputs/indicator_match.csv','EPA WFD regional context https://gis.epa.ie/ContactUs/Policy']);
}
// 6. Historical reconciliation and failed validation.
{
 const s=slide('Historical habitat changes the restoration question',6);
 await image(s,path.join(root,'outputs/overnight_20261013/qa/map_survey_priorities.png'),64,166,720,432,'Indicative survey priorities with historical Laminaria reference, not confirmed restoration sites.');
 text(s,'79 / 126',840,174,377,100,68,C.purple,SERIF);
 text(s,'old candidates overlap\nhistorical Laminaria\nat their centres',846,289,370,105,28);
 text(s,'Revisit condition and resolve\nreference conflicts first.',846,431,370,100,28,C.ink);
 text(s,'Legacy external FPR: 63.45%\nAcceptance threshold: 30%',846,546,370,80,23,C.muted);
 text(s,'© OpenStreetMap contributors and NPWS. Indicative investigation priorities, low confidence.',69,608,735,38,16,C.muted);
 const n='Restoration is where better reference data changed the interpretation. Seventy-nine of one hundred and twenty-six old candidate centres overlap the more specific historical Laminaria map. Those locations call for revisiting condition rather than assuming the habitat was absent. The earlier classifier failed its external false-positive criterion. The historical conflicts also question some old test labels, so we cannot present that old error rate as a new validation result. The application therefore shows low-confidence investigation priorities, not approved restoration sites. Field confirmation and corrected reference labels come before management recommendations.';
 notes.push(n);note(s,n,['NPWS Roaringwater Bay and Islands SAC marine supporting document, 2011, https://www.npws.ie/sites/default/files/publications/pdf/000101_Roaringwater%20Bay%20and%20Islands%20SAC%20Marine%20Supporting%20Doc_V1.pdf','NPWS SSCO package March 2025; dates reflect older 2002, 2004, 2009 and 2010 surveys, exact polygon dates unknown','outputs/model/model_multisite_report.json; prior external false-positive rate .6345, threshold .30; no claim of retraining','Centre-overlap definition in src/evidence_pipeline.py']);
}
// 7. Honest transfer gate and concrete next evidence.
{
 const s=slide('The next useful evidence comes from Cork',7);
 text(s,'A working local prototype',65,167,620,52,32,C.green,SERIF);
 text(s,'Clickable habitat evidence\nConditional wave physics\nEditable euro scenarios\nBiodiversity and survey priorities',70,241,606,222,29);
 text(s,'Mizen transfer test',725,167,486,52,32,C.green,SERIF);
 text(s,'556 assessed model cells\n0 pass the retained threshold\nResult: no estimate',730,241,480,157,29);
 text(s,'This is a data and model gate.\nIt does not prove kelp absence.',731,425,480,93,23,C.muted);
 text(s,'Next: verify species and density, measure waves across habitat, then validate hazard at receptors.',69,548,1145,86,32,C.ink,SERIF);
 const n='The prototype runs locally and keeps the evidence attached to each result. A second Cork segment demonstrates the same screening logic. At Mizen, none of the five hundred and fifty-six assessed cells pass the retained threshold. The pipeline returns no estimate, which is a useful test of transfer limits rather than proof that kelp is absent. The next practical step is a targeted Cork validation partnership: check habitat species and density, measure waves across it, and connect the transformed hazard to receptor values and damage functions. That is the evidence needed to move from an illustrative cost comparison to a defensible estimate of avoided damage.';
 notes.push(n);note(s,n,['Reusable local command: python src/run_segment.py --site mizen_outer','Current primary study remains Sherkin / West Cork. France archive is supplementary only.','No external publication or upload has been performed. Field and economic validation remain outstanding.']);
}
await fs.writeFile(path.join(work,'speaker_notes.json'),JSON.stringify(notes,null,2));
for(const [i,s] of p.slides.items.entries()){
 const b=await p.export({slide:s,format:'png',scale:1});await fs.writeFile(path.join(work,'slide-'+String(i+1).padStart(2,'0')+'.png'),new Uint8Array(await b.arrayBuffer()));
 const layout=await s.export({format:'layout'});await fs.writeFile(path.join(work,'slide-'+(i+1)+'.layout.json'),await layout.text());
}
const candidate=path.join(work,'candidate.pptx');await (await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=path.join(out,'Invisible_Shield_Jury_FINAL.pptx');
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath,
 pythonExecutable:path.join(runtime,'python/python.exe'),
 integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','4'],
 explicitTotalSlideCount:7,requiredNativeTableOwnerSlides:[4],requiredNativeChartOwnerSlides:[3,5],materializeLiteralChartWorkbooks:true,
 fontPolicy:{basis:'design',families:[FONT,SERIF]},verifyArtifactToolImport:true,
 receiptPath:path.join(work,'validation-final.json')});
console.log(JSON.stringify({status:result.status||'completed',file:finalPath,slides:7}));
