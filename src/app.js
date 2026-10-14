/* Ocean Hackathon Cork. Computed evidence is embedded by build_map.py. */
(function(){
'use strict';
const $=id=>document.getElementById(id), text=(id,value)=>{if($(id))$(id).textContent=value;};
const number=(v,d=1)=>v==null?'Not quantified':Number(v).toLocaleString('en-IE',{maximumFractionDigits:d,minimumFractionDigits:d});
const pct=v=>v==null?'Not computable':number(v*100,1)+'%';
const money=v=>new Intl.NumberFormat('en-IE',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(v);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const human=v=>String(v).toLowerCase().replace(/_/g,' ');
const physical=D.physical, site=D.site;
let activePhysical=physical, activeArea=site.area_ha, activeGroup=0, ready=false;
text('summary-area',number(site.area_ha,2)+' ha');
text('summary-groups',site.cell_count+' model cells in '+site.group_count+' separate groups');
text('summary-wave',pct(physical.height_fraction));
text('summary-bio',D.biodiversity?D.biodiversity.present+' of '+D.biodiversity.total:'Unavailable');
text('height-effect',pct(physical.height_fraction));text('energy-effect',pct(physical.energy_fraction));text('intercept',number(physical.wave_intercept_m,0)+' m');
text('physical-meaning','Across the union of the seven assumed cells at LAT. Mean habitat path '+number(physical.path_m_mean,1)+' m. The '+number(physical.envelope_width_m,0)+' m envelope spans gaps; neither width is a measured protected coastline.');
text('wave-path-copy','Offshore direction from '+number(D.wave.from_deg,1)+'° (travel '+number(D.wave.travel_deg,1)+'°). Straight paths are screened against OSM coastline; nearshore rotation remains unknown.');
text('shoreline-copy',number(D.shoreline.candidate_frontage_m,0)+' m of candidate shoreline in the geometric screen, sampled at ≤'+D.shoreline.step_m+' m. Verified protected frontage remains not quantified.');
text('legacy-copy','Audit trail: the earlier grid-axis baseline was '+D.legacy.wave_height_pct+'% height / '+D.legacy.wave_energy_pct+'% energy. The new polygon-ray result is '+pct(physical.height_fraction)+' / '+pct(physical.energy_fraction)+'. The fitted-coefficient cross-check gives '+pct(physical.fitted_crosscheck.height_fraction)+' height reduction. These are different declared model constructions, not new field measurements.');
$('physical-limits').innerHTML=physical.conditions.map(v=>'<li>'+esc(v)+'</li>').join('');
text('build-stamp','Evidence build '+D.build_date+' · '+D.build_id);
text('map-evidence-note',D.intertidal?number(D.intertidal.area_ha,1)+' ha satellite intertidal proxy from '+D.intertidal.n_scenes+' scenes in '+D.intertidal.year+'. Detected signal; unvalidated, species-agnostic extent.':'Satellite layer unavailable in this build.');

function bars(id,rows,formatter=number){
 const max=Math.max(...rows.map(r=>r.value),.000001);
 $(id).innerHTML=rows.map(r=>'<div class="bar-row"><span>'+esc(r.label)+'</span><div class="bar-track"><span class="bar-fill" style="width:'+Math.max(0,Math.min(100,r.value/max*100))+'%"></span></div><span class="bar-value">'+esc(formatter(r.value))+'</span></div>').join('');
}
bars('direction-chart',physical.direction_sensitivity.filter(r=>r.height_fraction!=null).map(r=>({label:(r.offset_deg>0?'+':'')+r.offset_deg+'°',value:r.height_fraction})),pct);
$('tide-table').innerHTML=physical.tide_sensitivity.map(r=>'<tr><td>+'+number(r.water_level_above_LAT_m,0)+' m</td><td>'+pct(r.coverage_fraction)+'</td><td>'+esc(pct(r.height_fraction))+'</td></tr>').join('');

function waveGraphic(withKelp){
 const amplitude=withKelp&&activePhysical.height_fraction!=null?1-activePhysical.height_fraction:1;
 function path(start,end,amp){let s='';for(let x=start;x<=end;x+=2){const y=90-Math.sin((x-20)*Math.PI/55)*26*amp;s+=(x===start?'M':'L')+x.toFixed(1)+' '+y.toFixed(2)+' ';}return s;}
 $('wave-before').setAttribute('d',path(25,245,1));$('wave-after').setAttribute('d',path(250,655,amplitude));
 $('kelp-drawing').style.opacity=withKelp?'1':'.12';text('wave-output',withKelp&&activePhysical.height_fraction==null?'Outside model domain':number(amplitude*100,1)+'% relative outgoing height');
 for(const [id,selected] of [['with-kelp',withKelp],['without-kelp',!withKelp]]){$(id).classList.toggle('active',selected);$(id).setAttribute('aria-pressed',String(selected));}
}
$('with-kelp').onclick=()=>waveGraphic(true);$('without-kelp').onclick=()=>waveGraphic(false);waveGraphic(true);


function refreshPhysical(){
 text('height-effect',activePhysical.height_fraction==null?'Unknown':number(activePhysical.height_fraction*100,2)+'%');text('energy-effect',activePhysical.energy_fraction==null?'Unknown':number(activePhysical.energy_fraction*100,2)+'%');text('intercept',number(activePhysical.wave_intercept_m,0)+' m');
 const scope=activeGroup?'Sherkin model group '+activeGroup:'Roaringwater pilot / all seven cells';
 text('physical-scope',scope+' / '+number(activeArea,2)+' ha / polygon-ray model at LAT');
 text('economic-scope','Scenario footprint: '+scope+' / '+number(activeArea,2)+' ha');
 text('physical-meaning','Within the selected assumed habitat. Mean ray path '+number(activePhysical.path_m_mean,1)+' m. This is not a measured reduction at the shore. The sensitivity appendix describes the whole pilot.');
 waveGraphic(true);
 $('wave-comparison').innerHTML=activePhysical.height_fraction==null?'<p>With-habitat estimate unavailable: some paths leave the supported model domain. No zero attenuation is substituted.</p>':'<div><span>Without assumed kelp</span><div class="comparison-track"><i style="width:100%"></i></div><strong>100%</strong></div><div><span>With assumed kelp</span><div class="comparison-track"><i style="width:'+((1-activePhysical.height_fraction)*100)+'%"></i></div><strong>'+number((1-activePhysical.height_fraction)*100,2)+'%</strong></div><p>Relative outgoing wave height (%). Same incident wave; conditional model.</p>';
}

function inspectGroup(props){
 activeGroup=props?.group_id||0;activePhysical=props||physical;activeArea=props?.area_ha??site.area_ha;
 if(ready){updateCost();refreshPhysical();}
 window.dispatchEvent(new CustomEvent('shield:selection',{detail:activeGroup}));
 const all=!props, area=all?site.area_ha:props.area_ha, h=all?physical.height_fraction:props.height_fraction;
 text('area-title',all?'Sherkin model pilot':'Model group '+props.group_id);
 text('area-status','MODELLED · UNVALIDATED');
 text('area-description',(all?site.cell_count:props.cells)+' nominal 50 m cells. A suitability model proposes subtidal habitat; current L. hyperborea and density have not been confirmed.');
 const plausible=all?(D.assets.counts.DIRECTIONALLY_PLAUSIBLE_UNVALIDATED||0):props.plausible_asset_records;
 const facts=[['Model footprint',number(area,2)+' ha'],['Baseline within-habitat height effect',pct(h)],['Baseline possible receptors',plausible+' mapped records; unvalidated'],['Actual avoided damage','Not quantified'],['Conditional cost scenario','Selected footprint, adjustable assumptions below'],['Biodiversity / condition',(D.biodiversity?D.biodiversity.present+' of '+D.biodiversity.total:'Unknown')+' regional taxa; decline unknown'],['Restoration status','Survey first; not confirmed']];
 $('area-facts').innerHTML=facts.map(([k,v])=>'<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>').join('');
}
inspectGroup(null);
function inspectEvidence(title,label,description,more){text('area-title',title);text('area-status',label);text('area-description',description);$('area-facts').innerHTML=more.map(([a,b])=>'<div><dt>'+esc(a)+'</dt><dd>'+esc(b)+'</dd></div>').join('');}

const map=L.map('map',{scrollWheelZoom:false,preferCanvas:false,minZoom:10,maxZoom:19}).setView([51.465,-9.405],15);
map.attributionControl.setPrefix('<a href="https://leafletjs.com/">Leaflet</a>');
map.attributionControl.addAttribution('© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> · NPWS · Copernicus · EMODnet');
L.control.scale({imperial:false}).addTo(map);
map.createPane('depth');map.getPane('depth').style.zIndex=200;
map.createPane('land');map.getPane('land').style.zIndex=250;
L.geoJSON(D.coastline.land,{pane:'land',style:{color:'#91a896',weight:1,fillColor:'#e9e8d8',fillOpacity:1},interactive:false}).addTo(map);
L.geoJSON(D.coastline.coast,{pane:'land',style:{color:'#758e80',weight:1.2},interactive:false}).addTo(map);
for(const [name,lat,lon] of [['Sherkin Island',51.4677,-9.4094],['Atlantic Ocean',51.461,-9.400],['Baltimore',51.483,-9.371]])L.marker([lat,lon],{interactive:false,icon:L.divIcon({className:'map-label',html:esc(name),iconSize:[130,20]})}).addTo(map);
const layers={}, groupLayers=new Map();
layers.model=L.featureGroup();
L.geoJSON(D.groups,{style:{color:'#174e43',weight:2,fillColor:'#267963',fillOpacity:.62},onEachFeature:(f,l)=>{const p=f.properties;groupLayers.set(p.group_id,l);l.on('click',()=>inspectGroup(p));l.bindPopup('<h3>Model group '+p.group_id+'</h3><b>Modelled · unvalidated</b><br>'+number(p.area_ha,2)+' ha / '+p.cells+' cells<br>Baseline height attenuation: '+pct(p.height_fraction)+'<br>Actual avoided damage: not quantified');}}).addTo(layers.model);
for(const f of D.groups.features){const p=f.properties,g=L.geoJSON(f);const m=L.marker(g.getBounds().getCenter(),{icon:L.divIcon({className:'group-label',html:String(p.group_id),iconSize:[28,28]}),title:'Select model group '+p.group_id,keyboard:true});m.on('click',()=>{inspectGroup(p);groupLayers.get(p.group_id).openPopup();});layers.model.addLayer(m);}
layers.model.addTo(map);
if(D.intertidal)layers.intertidal=L.geoJSON(D.intertidal.extent,{style:{color:'#346f94',weight:1,fillOpacity:.6},onEachFeature:(f,l)=>l.on('click',()=>inspectEvidence('Intertidal macroalgae','DETECTED SIGNAL · UNVALIDATED', 'Sentinel-2 tide-response vegetation proxy. It does not identify species or confirm subtidal Laminaria hyperborea.',[['AOI proxy extent',number(D.intertidal.area_ha,1)+' ha'],['Evidence dates',D.intertidal.n_scenes+' scenes, '+D.intertidal.year],['Coastal value','Not estimated for this layer'],['Condition and restoration','No repeated extent / no management recommendation']]))});
layers.historical=L.geoJSON(D.historical.layer,{style:{color:'#8364a0',weight:1.5,fillOpacity:.14,dashArray:'5 4'},onEachFeature:(f,l)=>{l.bindPopup('<b>'+esc(f.properties.community)+'</b><br>Historical reference, not current extent.');l.on('click',()=>inspectEvidence('Historical Laminaria','HISTORICAL REFERENCE',f.properties.survey_context,[['Release',f.properties.release],['Current condition','Unknown; revisit needed'],['Species specificity','Laminaria community; not verified L. hyperborea'],['Coastal value','No separate value attributed']]));}});
layers.restoration=L.geoJSON(D.historical.restoration,{style:f=>({color:f.properties.historical_overlap?'#8364a0':'#ad712c',weight:1,fillOpacity:.35}),onEachFeature:(f,l)=>{l.bindPopup('<b>'+esc(f.properties.action)+'</b><br>Low confidence. Not a management recommendation.');l.on('click',()=>inspectEvidence('Survey priority','INDICATIVE · LOW CONFIDENCE',f.properties.action,[['Historical area overlap',pct(f.properties.overlap_fraction)],['Suitability score',number(f.properties.suitability,3)+' (not a calibrated probability)'],['Restoration status','Not confirmed'],['Coastal value','Not quantified']]));}});
layers.assets=L.geoJSON(JSON.parse(JSON.stringify(D.assets.layer)),{pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:4}),style:f=>({color:f.properties.status==='DIRECTIONALLY_PLAUSIBLE_UNVALIDATED'?'#ad712c':'#8d5840',weight:1.6,fillOpacity:.5}),onEachFeature:(f,l)=>{const p=f.properties;l.bindPopup('<b>'+esc(p.name||p.osm_id)+'</b><br>'+esc(p.kind)+'<br>'+esc(human(p.status))+'<br>Distance '+number(p.distance_m,0)+' m<br>No damage value assigned.<br><a href="https://www.openstreetmap.org/'+esc(p.osm_id)+'" target="_blank" rel="noopener noreferrer">OSM source</a>');l.on('click',()=>inspectEvidence(p.name||p.osm_id,'MAPPED ASSET · ATTRIBUTION UNVALIDATED',human(p.status),[['Type',p.kind],['Distance to selected group',number(p.distance_m,0)+' m'],['Wave-path angle difference',number(p.angle_difference_deg,1)+'°'],['Actual avoided damage','Not quantified']]));}});
layers.paths=L.featureGroup([L.geoJSON(D.assets.paths,{style:{color:'#ad712c',weight:1.5,dashArray:'5 6'}}),L.geoJSON(D.shoreline.layer,{style:{color:'#b46030',weight:5},onEachFeature:(f,l)=>l.bindPopup('Candidate shoreline, not verified protected frontage.')} )]);
layers.bathymetry=L.geoJSON(D.bathymetry.layer,{pane:'depth',style:f=>({stroke:false,fillColor:{1:'#b9dbd5',2:'#95bdc9',3:'#6894ac',4:'#476d89'}[f.properties.depth_band],fillOpacity:.65}),onEachFeature:(f,l)=>l.bindPopup('Depth context '+esc(f.properties.label)+'<br>Coarse EMODnet grid, about 290 × 464 m. Not nearshore survey resolution.')});
layers.satellite=L.imageOverlay('sentinel-context.png',[[site.bbox[1],site.bbox[0]],[site.bbox[3],site.bbox[2]]],{opacity:.85,pane:'depth'});
if(D.biodiversity)layers.biodiversity=L.featureGroup(D.biodiversity.sites.map(s=>L.circleMarker([s.lat,s.lon],{radius:5,color:'#50676b',fillColor:'#fff',fillOpacity:1,weight:1.5}).bindPopup('<b>Dive-site context</b><br>'+s.indicators+' reference taxa recorded<br>'+s.records+' occurrence records<br>Effort-biased; not a trend.')));
if(D.exposure)layers.exposure=L.geoJSON(D.exposure.points,{pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:5,color:'#a46b40',weight:1,fillOpacity:.65}),onEachFeature:(f,l)=>l.bindPopup('Relative exposure index: '+number(f.properties.EI,2)+'<br>Ordinal context. Not wave attenuation or monetary value. Habitat proximity is a ranking assumption, not a screened wave path.')});
document.querySelectorAll('[data-layer]').forEach(input=>{const name=input.dataset.layer;if(!layers[name]){input.disabled=true;input.closest('label').title='Source unavailable in this build';return;}input.addEventListener('change',()=>input.checked?map.addLayer(layers[name]):map.removeLayer(layers[name]));});
function toggleLayer(name,on){const input=document.querySelector('[data-layer="'+name+'"]');if(input&&!input.disabled){input.checked=on;input.dispatchEvent(new Event('change'));}}
function pilot(){map.closePopup();map.fitBounds(layers.model.getBounds().pad(.65));inspectGroup(null);}
$('focus-pilot').onclick=pilot;$('reset-map').onclick=()=>{for(const el of document.querySelectorAll('[data-layer]'))toggleLayer(el.dataset.layer,el.dataset.layer==='model');pilot();};
$('focus-cork').onclick=()=>{map.fitBounds([[site.bbox[1],site.bbox[0]],[site.bbox[3],site.bbox[2]]]);toggleLayer('intertidal',true);toggleLayer('historical',true);};
let tileLayer=null;
$('online-tiles').onchange=()=>{if($('online-tiles').checked){tileLayer=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors',referrerPolicy:'strict-origin-when-cross-origin'});tileLayer.on('tileerror',()=>{if(tileLayer&&map.hasLayer(tileLayer))map.removeLayer(tileLayer);$('online-tiles').checked=false;text('map-mode','Online tiles unavailable; local geography retained');});tileLayer.on('load',()=>{if($('online-tiles').checked)text('map-mode','Online OSM tiles with local evidence');});tileLayer.addTo(map);}else{if(tileLayer)map.removeLayer(tileLayer);text('map-mode','Offline geography ready');}};
window.addEventListener('offline',()=>{if(tileLayer)map.removeLayer(tileLayer);$('online-tiles').checked=false;text('map-mode','Offline: all core evidence remains available');});
$('group-buttons').innerHTML=D.groups.features.map(f=>'<button type="button" data-group="'+f.properties.group_id+'">Group '+f.properties.group_id+'</button>').join('');
document.querySelectorAll('[data-group]').forEach(b=>b.onclick=()=>{const f=D.groups.features.find(f=>f.properties.group_id===Number(b.dataset.group));toggleLayer('model',true);map.fitBounds(groupLayers.get(f.properties.group_id).getBounds().pad(2));inspectGroup(f.properties);groupLayers.get(f.properties.group_id).openPopup();});
text('assets-summary',D.assets.mapped_records+' built/infrastructure records screened from '+D.assets.inventory_records+' inventory objects. '+(D.assets.counts.DIRECTIONALLY_PLAUSIBLE_UNVALIDATED||0)+' are directionally plausible under the declared screen. Object counts are not independently damaged assets.');
$('assets-table').innerHTML=[...D.assets.layer.features].sort((a,b)=>a.properties.distance_m-b.properties.distance_m).map(f=>{const p=f.properties;return '<tr><td><a href="https://www.openstreetmap.org/'+esc(p.osm_id)+'" target="_blank" rel="noopener noreferrer">'+esc(p.name||p.osm_id)+'</a></td><td>'+esc(p.kind)+'</td><td>'+esc(human(p.status))+'</td><td>'+number(p.distance_m,0)+' m</td></tr>';}).join('');

function calculateCost(area,width,share,rate,years,rates){
 const vals=[area,width,share,rate,years,rates.low,rates.project_pooled,rates.high];
 if(vals.some(v=>typeof v!=='number'||!Number.isFinite(v))||area<=0||width<=0||share<0||share>1||rate<0||rate>1||years<=0||years>1000||rates.low<=0||rates.low>rates.project_pooled||rates.project_pooled>rates.high)throw new Error('Enter finite values. Width, life and funding rates must be positive. Share and discount must be between 0 and 100%.');
 const crf=rate===0?1/years:rate/(-Math.expm1(-years*Math.log1p(rate))),length=area/width,bands={};
 for(const key of ['low','project_pooled','high']){const full=length*rates[key];bands[key]={full,pro:full*share,annual:full*share*crf};}
 return {length,bands,capital_recovery_factor:crf};
}
let currentCost=null;
function updateCost(){
 try{
  const read=id=>{if($(id).value.trim()==='')throw new Error('An input is blank. No monetary result is displayed.');return Number($(id).value);};
  const width=read('cc-width'),share=read('cc-effect')/100,rate=read('cc-rate')/100,years=read('cc-life');
  const result=calculateCost(activeArea*10000,width,share,rate,years,D.costs.rates),range=k=>money(result.bands.low[k])+' – '+money(result.bands.high[k]);
  text('cc-pro',range('pro'));text('cc-annual',range('annual')+' / year');text('cc-full',range('full')+' one-off');text('cc-length',number(result.length,1)+' m (assumed comparison)');
  $('cc-values').hidden=false;$('cc-error').hidden=true;$('cc-download').disabled=false;
  bars('cost-sensitivity',[50,100,150,200].map(w=>({label:w+' m',value:calculateCost(activeArea*10000,w,share,rate,years,D.costs.rates).bands.project_pooled.annual})),v=>money(v)+'/yr');
  currentCost={status:'CONDITIONAL_COST_SCENARIO_NOT_AVOIDED_DAMAGE',build_id:D.build_id,assessment_group:activeGroup,model_area_m2:activeArea*10000,assumed_cross_shore_width_m:width,cost_scaling_share:share,discount_rate:rate,lifetime_years:years,frontage_is_measured:false,avoided_damage_eur:null,annual_avoided_damage_eur:null,kelp_service_value_eur:null,...result,rates:D.costs.rates,sources:D.costs.sources,limitations:D.costs.limitations};
 }catch(e){currentCost=null;text('cc-error',e.message);$('cc-error').hidden=false;$('cc-values').hidden=true;$('cc-download').disabled=true;}
}
for(const id of ['cc-width','cc-effect','cc-rate','cc-life'])$(id).addEventListener('input',updateCost);
$('cost-form').onsubmit=e=>e.preventDefault();
$('cc-reset').onclick=()=>{for(const [id,v] of [['cc-width',100],['cc-effect',D.costs.default.energy_reduction_fraction_parameter*100],['cc-rate',4],['cc-life',50]])$(id).value=v;updateCost();};
$('use-physical').onclick=()=>{if(activePhysical.energy_fraction==null)return;$('cc-effect').value=(activePhysical.energy_fraction*100).toFixed(3);updateCost();};
$('cc-download').onclick=()=>{if(!currentCost)return;const blob=new Blob([JSON.stringify(currentCost,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='coastal_cost_scenario.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);};
$('cc-reset').click();ready=true;refreshPhysical();
text('cost-source-copy','Approved funding per metre: '+money(D.costs.rates.low)+'–'+money(D.costs.rates.high)+', pooled '+money(D.costs.rates.project_pooled)+'. Recomputed from €668,921 / 155 m, €657,338 / 100 m and €500,535 / 70 m, at one Wexford site.');
window.CoastalCostCalculator=Object.freeze({version:'2.0',calculate:calculateCost,getResult:()=>currentCost?JSON.parse(JSON.stringify(currentCost)):null});

function annualChart(id,rows,key,unit){
 if(!rows.length){$(id).innerHTML='<p class="note">No compatible data available. Missing values are not zero.</p>';return;}
 const max=Math.max(...rows.map(r=>Math.abs(r[key])),.001);
 $(id).innerHTML=rows.map(r=>'<div class="annual-col"><span class="value">'+number(r[key],1)+unit+'</span><span class="bar" style="height:'+Math.max(1,Math.abs(r[key])/max*130)+'px;background:'+(r[key]<0?'#718ca2':'#3e716e')+'" title="'+r.year+': '+number(r[key],2)+unit+'; coverage '+pct(r.coverage_fraction)+'"></span><span class="year">'+r.year+'</span></div>').join('');
}
text('wave-climate-copy','Nearest wet grid point is '+number(D.wave.distance_to_model_centroid_m/1000,2)+' km from the pilot centroid. Median Hs '+number(D.wave.hs_median_m,2)+' m; 95th percentile '+number(D.wave.hs_p95_m,2)+' m across '+D.wave.first_date+' to '+D.wave.last_date+'.');
annualChart('wave-chart',D.wave.annual,'hs_mean_m','m');
text('sst-copy',D.sst.annual.length?D.sst.source+' at '+number(D.sst.distance_to_bed_m/1000,1)+' km from the pilot. '+D.sst.sampling+'.':'SST currently unavailable for this pilot.');
text('sst-note',D.sst.note+(D.sst.baseline?' Baseline: '+D.sst.baseline+'.':''));
annualChart('sst-chart',D.sst.annual,'mean_c','°');
if(D.biodiversity){
 const b=D.biodiversity;text('bio-count',b.present+' of '+b.total);
 $('bio-dots').innerHTML=b.taxa.map(t=>'<span role="img" class="taxa-dot'+(t.present_in_west_cork?'':' empty')+'" aria-label="'+esc(t.accepted_name)+': '+(t.present_in_west_cork?'recorded':'unrecorded')+'" title="'+esc(t.accepted_name)+'"></span>').join('');
 text('bio-method','Reference list: Schoenrock et al. (2020), taxonomic reconciliation through WoRMS, regional occurrence compilation across '+b.sites.length+' sites. The indicator counts distinct reference taxa. It does not normalise sampling effort sufficiently to compare habitat condition between sites.');
 $('taxa-list').innerHTML=b.taxa.map(t=>'<div class="taxon"><i>'+esc(t.accepted_name)+'</i> · '+(t.present_in_west_cork?'recorded at '+t.n_sites_of_35+' reference sites':'unrecorded')+'</div>').join('');
}
const epa=(D.epa?.features||[]).find(f=>f.properties.code==='IE_SW_140_0000');
if(epa)$('epa-timeline').innerHTML=Object.entries(epa.properties.status).map(([year,s])=>'<span class="epa-chip">'+esc(year)+'<strong>Overall '+esc(s.overall)+'</strong><span>Macroalgae '+esc(s.macroalgae||'not published')+'</span></span>').join('');
text('historical-match',D.historical.historical_centre_matches+' / '+D.historical.disputed_cells);
text('restoration-reconcile','The site-specific NPWS reference changes the interpretation of these old “restoration” cells. Historical overlap calls for a condition revisit. The remaining cells need reference checks and field survey; a suitable model score does not prove habitat loss.');
text('validation-copy','The legacy external false-positive rate was '+pct(D.historical.fpr_prior)+' against a 30% acceptance threshold. '+D.historical.fpr_note);
$('validation-bar').style.width=(D.historical.fpr_prior*100)+'%';
$('show-restoration').onclick=()=>{toggleLayer('restoration',true);toggleLayer('historical',true);map.fitBounds(layers.restoration.getBounds().pad(.15));$('explore').scrollIntoView();};
text('france-copy',D.france?'The archived Iroise / Le Conquet run processed '+number(D.france.cells_in_band,0)+' habitat cells within its specified depth band. Local saturation, tidal datum and shoreline-connection assumptions remain limitations.':'Archived France inputs unavailable in this build.');
text('transfer-copy',D.transfer?D.transfer.summary:'The same geometry and depth engine accepts another local segment; see the reproducible run_segment.py command in the handover.');
$('transfer-run').onclick=()=>{$('transfer-result').hidden=!$('transfer-result').hidden;text('transfer-result',D.transfer?'Local grid: '+number(D.transfer.grid_cells,0)+' cells. Assessed: '+number(D.transfer.assessed_cells,0)+'. Above threshold: '+D.transfer.above_threshold+'. '+D.transfer.note:'No transfer result in this build.');};
$('source-list').innerHTML=D.sources.map(s=>'<div class="source-row"><div><h3>'+esc(s.name)+'</h3><p class="source-kind">'+esc(s.role)+'</p><p>'+esc(s.dates)+'</p><a href="'+esc(s.url)+'" target="_blank" rel="noopener noreferrer">Source and terms ↗</a></div><div><p>'+esc(s.limits)+'</p><p class="quiet">'+esc(s.attribution)+' · '+esc(s.licence)+'</p></div></div>').join('');
text('optional-warnings',D.warnings.length?'Unavailable optional sources: '+D.warnings.map(w=>w.layer).join(', ')+'. No substitute values have been invented.':'All required local input readers completed. Scientific limitations remain separate from software availability.');
window.ShieldApp=Object.freeze({applyCost:r=>{currentCost=r;},applyModel:r=>{activePhysical=r;refreshPhysical();},getAssessment:()=>({group:activeGroup,area_ha:activeArea,physical:activePhysical}),version:3,buildId:D.build_id,map,layers,evidence:D,selectGroup:id=>{const f=D.groups.features.find(f=>f.properties.group_id===id);if(f)inspectGroup(f.properties);}});
pilot();
})();
