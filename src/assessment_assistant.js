/* Shared browser/Node evidence retrieval and answer compiler. No network or eval. */
(function(root){'use strict';
const tokens=s=>String(s).toLowerCase().match(/[a-z0-9]+/g)||[];
const f=(x,d=2)=>Number.isFinite(x)?x.toLocaleString('en-IE',{maximumFractionDigits:d}):'not assessed';
const defaults={water_level_m:0,coefficient_multiplier:1,method:'interpolated',cost_share:1,rate_multiplier:1,discount_rate:.04,years:50,length_mode:'fixed_frontage',frontage_m:100};
function context(data,state){
 const p=data.product,c=p.cases[state.case];if(!c)throw Error('Unknown assessment case');
 const inputs={...defaults,...state.inputs};let result=null,error=null;
 if(c.scenario){try{const d=c.scenario.directions[String(state.direction)];if(!d)throw Error('Select a valid direction');result=ParametricCoast.calculate(c.scenario,d,p.costs.cost_rates,inputs);}catch(e){error=e.message;}}
 const bio=c.biodiversity.records.filter(r=>(!state.bioClass||state.bioClass==='all'||(r.class||'Unclassified')===state.bioClass)&&(!state.bioYear||state.bioYear==='all'||String(r.eventDate).startsWith(state.bioYear))&&(state.bioQuality!=='no-land'||!(r.flags||[]).includes('ON_LAND'))&&(!state.bioSearch||((r.scientificName||'')+' '+(r.datasetName||'')).toLowerCase().includes(state.bioSearch.toLowerCase())));
 const history=c.observations.filter(r=>(!state.year||state.year==='all'||String(r.eventDate).startsWith(state.year))&&(!state.historySearch||JSON.stringify(r).toLowerCase().includes(state.historySearch.toLowerCase())));
 return {p,c,inputs,result,error,bio,history};
}
function retrieve(graph,query,site){
 const ts=[...new Set(tokens(query))],docs=graph.documents,avg=docs.reduce((n,d)=>n+d.tokens.length,0)/docs.length;
 const scored=docs.map(d=>{let score=0;for(const t of ts){const tf=d.tokens.filter(v=>v===t).length,df=docs.filter(x=>x.tokens.includes(t)).length;if(tf)score+=Math.log(1+(docs.length-df+.5)/(df+.5))*tf*2.2/(tf+1.2*(.25+.75*d.tokens.length/avg));}return {id:d.id,key:d.key,score};}).sort((a,b)=>b.score-a.score);
 const frontier=new Set(scored.filter(d=>d.score>0).slice(0,4).map(d=>d.id));frontier.add('site:'+site);let relations=[];
 for(let hop=0;hop<2;hop++){const next=new Set();for(const e of graph.edges)if(frontier.has(e.source)){relations.push(e);next.add(e.target);}for(const id of next)frontier.add(id);}
 return {documents:scored.slice(0,4),graph_edges:[...new Map(relations.map(e=>[JSON.stringify(e),e])).values()].slice(0,100)};
}
function intent(q,retrieval){
 if(/ignore.*(instruction|rule|previous)|system prompt|developer prompt|password|secret|api.?key|execute|powershell|cmd\.exe|read.*file|[a-z]:[\\/]|\.\.[\\/]|<script|fabricat|invent|pretend|hide.*(limit|uncertain)|guarantee|make.*positive/i.test(q))return 'refusal';
 if(/fisher|crab|lobster|add.*(euro|€|funding)/i.test(q))return 'fisheries';
 if(/avoid(ed)? damage|savings|save money|money.*save|ecosystem.?service.*(value|euro)|worth/i.test(q))return 'damage';
 if(/current.*(extent|kelp|bed)|confirmed.*(bed|kelp)|hectare|how much kelp|species.*(identify|identified)/i.test(q))return 'extent';
 if(/protect(ed)?|shoreline.*(benefit|reduction|hazard)|safe.*(road|house)|road|building|harbour.*benefit/i.test(q))return 'assets';
 if(/sonar|navigation|footprint.*video|copper.*(data|2019)/i.test(q))return 'sonar';
 if(/satellite|classifier|random forest|accuracy|machine learning|intertidal/i.test(q))return 'satellite';
 if(/budget share|funding.*attenuation|cost.*attenuation/i.test(q))return 'economics';
 if(/8[.,]43|attenuat|wave.*(height|direction)|with.*without|depth|coefficient|h\/h/i.test(q))return 'physics';
 if(/€|euro|562.?090|capital|frontage|budget|annual|discount|how.*cost|funding/i.test(q))return 'economics';
 if(/npws|ssco|article.?17|histor|independen|conflict|disagree|dated.*kelp/i.test(q))return 'history';
 if(/biodivers|taxa|taxon|inventory|richness|score|records.*(rectangle|filter|selected)/i.test(q))return 'biodiversity';
 if(/declin|risk|warming|storm|condition|health|trend|loss/i.test(q))return 'risk';
 if(/restor|next.*(step|action)|priorit|monitor|what.*evidence.*need/i.test(q))return 'priority';
 if(/why.*(cape|main|case|select)|compare.*(site|bantry)|bantry|long island/i.test(q))return 'site';
 if(/assistant|graphrag|local model|offline|citation|source behind|how.*system/i.test(q))return 'method';
 return 'unknown';
}
function answer(data,state,question,modelChoice=null){
 const q=String(question||'').trim().slice(0,1200),g=data.assistant_graph,ctx=context(data,state),{c,p,result:r,inputs:i}=ctx,retrieval=retrieve(g,q,state.case);let key=intent(q,retrieval);
 // Optional language model may resolve an unrecognised paraphrase only when
 // lexical retrieval has substantive support. It cannot override guardrails.
 if(key==='unknown'&&modelChoice&&retrieval.documents.some(d=>d.key===modelChoice&&d.score>=3))key=modelChoice;
 if(/source behind|source for this|evidence behind this/i.test(q))key=({1:'history',2:'physics',3:'economics',4:'biodiversity'})[state.stage]||'site';
 let doc=g.documents.find(d=>d.key===key),status='SUPPORTED',text='',limit='',action='',kind=doc?.result_type||'unavailable';
 const cape=state.case==='cape_clear';
 if(key==='refusal'||key==='unknown'){
   status='INSUFFICIENT_EVIDENCE';text=key==='refusal'?'I cannot execute commands, reveal private configuration, follow instructions inside evidence or manufacture a positive result.':'This assessment does not contain sufficient evidence to answer that question.';
   limit='The assistant only explains registered coastal assessment evidence and deterministic scenario outputs.';action='Ask about a mapped record, a selected scenario, its sources or the evidence needed for a decision.';
 }else if(key==='physics'){
   if(!r||ctx.error){status='NOT_APPLICABLE';text=ctx.error?'Correct the selected scenario inputs: '+ctx.error:'This supporting case has no local attenuation calculation.';}
   else if(r.height_fraction===null){status='INSUFFICIENT_EVIDENCE';text='The selected depth is outside the 4–10 m laboratory domain. Attenuation is unavailable, not zero.';}
   else{text='The selected scenario gives '+f(r.height_fraction*100,5)+'% wave-height attenuation within the assumed habitat cell. With habitat H/H₀ = '+f(r.with_relative_height,5)+'; without habitat H/H₀ = 1. Wave FROM '+state.direction+'°, chord '+f(r.path_m_mean)+' m; depth sensitivity +'+f(i.water_level_m)+' m.';
    if(cape&&/8[.,]43/.test(q)&&Math.abs(r.height_fraction-.08429535)>.00001)text+=' The 8.43% label belongs to the default Cape scenario; it is not the current selection.';
    if(c.scenario.directions[String(state.direction)].open_upwave_5km===false)text+=' The incoming screening ray crosses land; this is mathematical sensitivity only.';
   }
   limit='It does not establish shoreline wave reduction, protected buildings, measured kelp or avoided damage. Laboratory plants and the centre depth are assumptions; the Cape datum is unverified.';action='Confirm species/canopy, depth datum and nearshore transformation before assessing a receptor.';
 }else if(key==='economics'){
   if(!r){status='NOT_APPLICABLE';text=ctx.error?'Correct the selected inputs before calculating funding: '+ctx.error:'No local economic scenario is calculated for this supporting case.';}
   else{text='Selected pooled capital comparison: '+f(i.frontage_m)+' m × €'+f(r.bands.project_pooled.unit_eur_per_m,6)+'/m × '+f(i.cost_share*100)+'% independent share = €'+f(r.bands.project_pooled.capital_eur,2)+'. Low / pooled / high: €'+[r.bands.low.capital_eur,r.bands.project_pooled.capital_eur,r.bands.high.capital_eur].map(x=>f(x,2)).join(' / €')+'. Annual pooled capital equivalent: €'+f(r.bands.project_pooled.annualised_eur_per_year,2)+' at '+f(i.discount_rate*100)+'% over '+f(i.years)+' years.';}
   limit='Approved funding benchmarks are mixed nominal Wexford amounts, not a Cork quote, saved expenditure, kelp value or verified protected frontage. Wave attenuation never sets the share.';action='Keep the share independent; obtain site-specific lifecycle costs and receptor hazard evidence for a benefit appraisal.';
 }else if(key==='history'){
   status='PARTIALLY_SUPPORTED';text=c.history_note+' Selected dated observations: '+ctx.history.map(o=>(o.eventDate||'Undated')+' '+o.scientificName+' ['+(o.flags||[]).join(', ')+']').join('; ')+'.';
   limit='NPWS products and OBIS providers can reuse the same surveys. Dates or agreeing layers are not independent current validation; conflicting labels do not measure decline.';action='Inspect original survey lineage and obtain repeat georeferenced underwater observations.';
 }else if(key==='biodiversity'){
   text='The current rectangle and filters contain '+ctx.bio.length+' records and '+new Set(ctx.bio.map(x=>x.scientificName).filter(Boolean)).size+' distinct taxon names, from '+c.biodiversity.inventory_count+' archived geographic records. Filters: '+(state.bioClass||'all')+', '+(state.bioQuality||'all')+', year '+(state.bioYear||'all')+', search '+(state.bioSearch||'none')+'.';
   if(/score|richness|abundance/i.test(q))status='INSUFFICIENT_EVIDENCE';
   limit='These are provider occurrence records, not individuals, standardised bed richness or a biodiversity score. Habitat association and comparable effort are missing.';action='Review dates, coordinates and provider flags; design comparable kelp-associated sampling.';
 }else if(key==='site'){
   status='PARTIALLY_SUPPORTED';text=doc.text+' Current selection: '+c.name+'. '+c.history_note;limit='Site selection does not validate a present-day kelp bed, shoreline hazard or economic benefit.';action='Use Cape Clear for conditional integration and supporting cases for their explicitly bounded evidence.';
 }else if(key==='priority'){
   status='PARTIALLY_SUPPORTED';text=c.priorities.filter(x=>!state.priority||state.priority==='all'||x.id===state.priority).map(x=>x.id+': '+x.title+'. '+x.action).join(' ');limit='Research priorities are not restoration approval or evidence of measured degradation.';action='Assign ecology, GIS, engineering and economics owners to these evidence requirements.';
 }else{
   text=doc.text;
   if(['extent','assets','damage','risk','sonar','fisheries'].includes(key))status='INSUFFICIENT_EVIDENCE';
   limit=({extent:'A sampling cell or historical polygon cannot be relabelled as current kelp.',assets:'No specific road, building or harbour is shown to be protected.',damage:'The independent funding comparison cannot substitute for avoided damage.',risk:'Potential drivers do not establish a local decline trend.',sonar:'A documented campaign does not mean the experimental data are available.',fisheries:'Different valuations cannot be added without compatible scope and a causal benefit model.',satellite:'Diagnostic agreement is not present ecological accuracy.',method:'The model cannot create evidence, arithmetic or a validation claim.'})[key]||'No additional scientific inference is established.';
   action=({extent:'Survey current extent, species and canopy using georeferenced underwater observations.',assets:'Model nearshore transformation and with/without receptor hazard; verify asset elevations.',damage:'Supply event probabilities, receptor hazard, asset exposure and damage functions.',risk:'Collect repeat canopy transects and local temperature/clarity observations.',sonar:'Proceed with available evidence; obtain original WCD, navigation, footprint and video before sonar classification.',fisheries:'Keep fisheries context and engineering scenarios separate.',satellite:'Use frozen diagnostics to design independent spatial validation; do not transfer Sherkin scores.',method:'Open the cited report section and inspect the graph/index files.'})[key]||'Review the source evidence.';
 }
 const refs=(doc?.source_ids||[]).map(id=>p.sources.find(s=>s.id===id)).filter(Boolean).map(s=>({id:s.id,title:s.name,url:s.url,report_section:doc.section}));
 if(doc&&!refs.length)refs.push({id:'local-method',title:'Local assistant method and guardrail specification',url:null,report_section:11});
 return {schema:'shield-answer-1',build_id:data.build_id,case:state.case,question:q,status,result_type:kind,answer:text,evidence_used:doc?[{id:doc.id,title:doc.title,text:doc.text}]:[],source_references:refs,what_this_does_not_prove:limit,suggested_next_action:action,actions:doc?[{label:'Open report section',kind:'report',section:doc.section},{label:'Show assessment context on map',kind:'map',stage:['biodiversity','priority'].includes(key)?4:['physics','assets'].includes(key)?2:1}]:[],retrieval,topic:key,mode:'deterministic',selected_inputs:{...i},selected_filters:{year:state.year,bioClass:state.bioClass,bioQuality:state.bioQuality,bioYear:state.bioYear,bioSearch:state.bioSearch},numeric_result:r};
}
root.AssessmentAssistant=Object.freeze({answer,retrieve,context,defaults});
})(typeof window==='undefined'?globalThis:window);
