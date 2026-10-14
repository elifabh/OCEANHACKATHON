/* Four research journeys and an offline tour over the real evidence application. */
(function(){
'use strict';
const $=id=>document.getElementById(id), text=(id,v)=>{$(id).textContent=v;};
const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
const app=window.ShieldApp, d=app.evidence, story=d.story;
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>(v*100).toFixed(2)+'%';
const scroll=id=>$(id).scrollIntoView({behavior:reduced.matches?'instant':'smooth',block:'start'});
text('model-construction-note','Current polygon-ray model: '+fmt(d.physical.height_fraction)+' height / '+fmt(d.physical.energy_fraction)+' energy. Earlier grid-axis model: '+d.legacy.wave_height_pct+'% / '+d.legacy.wave_energy_pct+'%. Different model constructions, not successive field measurements. The cost fraction below remains a separate user assumption.');
const ireland=L.map('ireland-map',{zoomControl:false,scrollWheelZoom:false,dragging:false,doubleClickZoom:false,touchZoom:false,boxZoom:false,keyboard:false,attributionControl:false,zoomSnap:.1}).setView([53.35,-8.1],5.8);
L.geoJSON(d.ireland_context,{style:{color:'#809a95',weight:1.2,fillColor:'#dce6db',fillOpacity:1},interactive:false}).addTo(ireland);
let selectedSite='cork';const markers={};
for(const s of story.sites){
 markers[s.id]=L.circleMarker([s.lat,s.lon],{radius:s.id==='cork'?8:6,color:'#f7f5ed',weight:2,fillColor:s.id==='cork'?'#176655':'#7e6588',fillOpacity:1}).addTo(ireland).on('click',()=>selectSite(s.id));
 L.marker([s.lat,s.lon],{interactive:false,icon:L.divIcon({className:'context-place-label',html:esc(s.county),iconSize:[90,18],iconAnchor:[-12,9]})}).addTo(ireland);
}
$('site-buttons').innerHTML=story.sites.map(s=>'<button type="button" data-site="'+s.id+'" aria-pressed="false">'+esc(s.county)+'</button>').join('');
document.querySelectorAll('[data-site]').forEach(button=>button.onclick=()=>selectSite(button.dataset.site));
function selectSite(id){
 const s=story.sites.find(x=>x.id===id);if(!s)return;selectedSite=id;
 for(const [field,value] of Object.entries({role:s.role,name:s.name,why:s.why,evidence:s.evidence,calculated:s.calculated,limit:s.limit}))text('site-'+field,value);
 document.querySelectorAll('[data-site]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.site===id));b.classList.toggle('active',b.dataset.site===id);});
 Object.entries(markers).forEach(([key,m])=>m.setRadius(key===id?10:6));
 $('enter-cork').textContent=id==='cork'?'Zoom to the Cork pilot':'Return to the West Cork calculation';
}
selectSite('cork');
let zoomTimer;
function enterCork(){
 selectSite('cork');clearTimeout(zoomTimer);
 if(!reduced.matches)ireland.flyTo([51.465,-9.405],8.3,{duration:1.2});
 else ireland.setView([51.465,-9.405],8.3,{animate:false});
 zoomTimer=setTimeout(()=>{scroll('explore');$('focus-cork').click();},reduced.matches?0:1100);
}
$('enter-cork').onclick=enterCork;
$('explore-cta').onclick=e=>{e.preventDefault();scroll('explore');$('focus-cork').click();};
// Restore geographic context when the overview comes back into view.
new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting))ireland.setView([53.35,-8.1],5.8,{animate:false});},{threshold:.3}).observe($('places'));

let selectedGroup=1;
function decision(id){
 const g=d.groups.features.find(f=>f.properties.group_id===id)?.properties;if(!g)return;selectedGroup=id;
 text('decision-title','Sherkin model group '+id);
 text('decision-observation',g.cells+' model cells, '+g.area_ha.toFixed(2)+' ha. Current species and density are unconfirmed. '+g.plausible_asset_records+' mapped records pass the declared direction/land screen; that does not prove absence of benefit.');
 text('decision-now',story.selected_action.now);text('decision-next',story.selected_action.next);
}
decision(1);window.addEventListener('shield:selection',e=>decision(e.detail||1));
$('select-decision').onclick=()=>{const details=$('group-buttons').closest('details');details.open=true;document.querySelector('[data-group="'+selectedGroup+'"]').click();scroll('explore');};
$('download-decision').onclick=()=>{
 const g=d.groups.features.find(f=>f.properties.group_id===selectedGroup).properties;
 const result={status:'RESEARCH_SCREENING_NOT_A_MANAGEMENT_RECOMMENDATION',build_id:d.build_id,group:g,action_now:story.selected_action.now,measure_next:story.selected_action.next,biodiversity_scope:'Regional reference-taxon presence, effort-biased',measured_decline:null,actual_avoided_damage_eur:null,cost_scenario:window.CoastalCostCalculator.getResult(),limitations:d.physical.conditions};
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));a.download='west-cork-screening-group-'+selectedGroup+'.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),30000);
};
$('visual-credit-list').innerHTML=d.visual_credits.map(c=>'<p><strong>'+esc(c.author)+'</strong>: '+esc(c.caption)+' '+esc(c.changes)+'. <a href="'+esc(c.source)+'">Original source</a>; <a href="'+esc(c.terms)+'">'+esc(c.licence)+'</a>.</p>').join('')+'<p>The wave diagram is original and conceptual. Map evidence uses the dataset credits below. No restricted OPW flood geometry appears in the app or media.</p>';

let motion=!reduced.matches;
function motionState(){document.body.classList.toggle('motion-paused',!motion||reduced.matches);$('wave-motion').setAttribute('aria-pressed',String(motion&&!reduced.matches));text('wave-motion',reduced.matches?'Reduced motion enabled':motion?'Pause wave motion':'Play conceptual wave motion');$('wave-motion').disabled=reduced.matches;}
$('wave-motion').onclick=()=>{motion=!motion;motionState();};reduced.addEventListener('change',motionState);motionState();
document.querySelectorAll('[data-layer]').forEach(control=>control.addEventListener('change',()=>{if(!reduced.matches&&control.checked){const pane=app.map.getPanes().overlayPane;pane.animate([{opacity:.45},{opacity:1}],{duration:450});}}));
new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting){document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('current',a.hash==='#'+e.target.id));}},{rootMargin:'-20% 0px -50% 0px'}).observe($('explore'));
const observer=new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting)document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('current',a.hash==='#'+e.target.id));},{rootMargin:'-20% 0px -50% 0px'});
['condition','protection','restoration'].forEach(id=>observer.observe($(id)));

const steps=[
 {target:'places',title:'1 / Ireland, then West Cork',copy:'Three places play different roles. The working calculation belongs to Sherkin and Roaringwater Bay.',run:()=>{selectSite('cork');ireland.setView([53.35,-8.1],5.8,{animate:false});}},
 {target:'explore',title:'2 / Make the evidence visible',copy:'Blue is a satellite intertidal proxy. Green is modelled subtidal habitat. Purple is historical survey evidence.',run:()=>{$('focus-cork').click();}},
 {target:'condition',title:'3 / Describe life and condition',copy:(d.biodiversity?d.biodiversity.present+' of '+d.biodiversity.total:'Unavailable')+' reference taxa in regional records. Environmental indicators do not establish a measured loss of this bed.',run:()=>{}},
 {target:'protection',title:'4 / Test a physical illustration',copy:fmt(d.physical.height_fraction)+' height reduction inside assumed habitat. Wave direction, depth and local validation matter.',run:()=>{$('with-kelp').click();}},
 {target:'cost-form',title:'5 / Question the euro assumptions',copy:'Change the assumed width or cost fraction. Annualised capital is not annual savings. Actual avoided damage remains not quantified.',run:()=>{}},
 {target:'restoration',title:'6 / Choose the next field check',copy:'Use a selected Cork screening brief to plan habitat verification and paired wave measurements. Restoration remains an investigation.',run:()=>decision(selectedGroup)}
];
let active=false,paused=false,index=0,timer=null,endsAt=0;
function showStep(){const step=steps[index];text('tour-progress','GUIDED TOUR / '+(index+1)+' OF '+steps.length);text('tour-title',step.title);text('tour-copy',step.copy);step.run();scroll(step.target);text('tour-next',index===steps.length-1?'Finish':'Next');endsAt=Date.now()+10000;}
function stopTour(){active=false;clearInterval(timer);timer=null;$('tour-panel').hidden=true;clearTimeout(zoomTimer);$('start-tour').focus({preventScroll:true});}
function next(){if(index===steps.length-1){stopTour();return;}index++;showStep();}
function startTour(){stopTour();active=true;paused=false;index=0;$('tour-panel').hidden=false;text('tour-pause','Pause');showStep();timer=setInterval(()=>{if(!active||paused)return;const remaining=endsAt-Date.now();$('tour-bar').style.width=Math.max(0,remaining/100)+'%';if(remaining<=0)next();},100);}
$('start-tour').onclick=startTour;$('tour-stop').onclick=stopTour;$('tour-next').onclick=next;
$('tour-pause').onclick=()=>{paused=!paused;text('tour-pause',paused?'Resume':'Pause');if(!paused)endsAt=Date.now()+10000;};
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&active)stopTour();});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&active)stopTour();});
window.ShieldStory=Object.freeze({ireland,selectSite,enterCork,startTour,stopTour,next,decision,getState:()=>({active,paused,index,selectedSite,selectedGroup,reducedMotion:reduced.matches})});
})();
