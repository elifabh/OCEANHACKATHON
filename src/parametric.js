/* Pure offline assessment calculator; geospatial chords come from EPSG:2157. */
(function(root){'use strict';
const finite=(x,n,lo,hi)=>{if(typeof x!=='number'||!Number.isFinite(x)||x<lo||x>hi)throw Error(n+' is outside its allowed range.');return x;};
function coefficient(depth,method){
 if(depth<4||depth>10)return null;
 if(method==='fitted')return .0658*Math.exp(-.5*depth);
 if(method!=='interpolated')throw Error('Unknown coefficient method');
 const ds=[4,6,8,10],ks=[.0094,.0032,.0014,.0005];
 for(let i=1;i<4;i++)if(depth<=ds[i])return ks[i-1]+(depth-ds[i-1])/(ds[i]-ds[i-1])*(ks[i]-ks[i-1]);
}
function calculate(scope,direction,rates,input={}){
 const p={water_level_m:0,coefficient_multiplier:1,method:'interpolated',cost_share:1,rate_multiplier:1,discount_rate:.04,years:50,length_mode:'shoreline',assumed_width_m:100,...input};
 finite(p.water_level_m,'Water level',0,3);finite(p.coefficient_multiplier,'Damping multiplier',.5,1.5);finite(p.cost_share,'Cost share',0,1);finite(p.rate_multiplier,'Rate multiplier',.5,2);finite(p.discount_rate,'Discount rate',0,1);finite(p.years,'Lifetime',1,1000);finite(p.assumed_width_m,'Assumed width',1,10000);
 if(!['shoreline','assumed_width'].includes(p.length_mode))throw Error('Unknown comparison length method');
 if(!['interpolated','fitted'].includes(p.method))throw Error('Unknown coefficient method');
 let total=0,valid=0,h=0,e=0,path=0,min=1,max=0;const reasons=new Set();
 for(const ray of direction.rays){
  total+=ray.weight_m;let tau=0,ok=!ray.land_blocked;if(!ok)reasons.add('LAND_BETWEEN_HABITAT');
  for(const seg of ray.segments){path+=seg.length_m*ray.weight_m;const k=coefficient(seg.depth_m_LAT+p.water_level_m,p.method);if(k===null){ok=false;reasons.add('OUTSIDE_DEPTH_DOMAIN');}else tau+=k*seg.length_m*p.coefficient_multiplier;}
  if(ok){const dh=-Math.expm1(-tau);valid+=ray.weight_m;h+=dh*ray.weight_m;e+=-Math.expm1(-2*tau)*ray.weight_m;min=Math.min(min,dh);max=Math.max(max,dh);}
 }
 if(total<=0)throw Error('No geospatial ray input');
 const full=Math.abs(valid-total)<1e-6;
 const length=p.length_mode==='shoreline'?direction.shoreline.length_m:scope.area_m2/p.assumed_width_m;
 const crf=p.discount_rate===0?1/p.years:p.discount_rate/(-Math.expm1(-p.years*Math.log1p(p.discount_rate)));
 const bands={};for(const key of ['low','project_pooled','high']){finite(rates[key],'Unit rate',0,1e7);const unit=rates[key]*p.rate_multiplier,capital=length*unit*p.cost_share;bands[key]={unit_eur_per_m:unit,capital_eur:capital,annualised_eur_per_year:capital*crf};}
 return {status:full?'MODELLED_UNVALIDATED':'PARTIAL_MODEL_DOMAIN',height_fraction:full?h/total:null,energy_fraction:full?e/total:null,without_relative_height:1,with_relative_height:full?1-h/total:null,coverage_fraction:valid/total,wave_intercept_m:total,path_m_mean:path/total,height_ray_range:valid?[min,max]:null,invalid_reasons:[...reasons],bearing_deg:direction.bearing_deg,inputs:p,area_m2:scope.area_m2,comparison_length_m:length,comparison_length_status:p.length_mode==='shoreline'?'GEOMETRIC_CANDIDATE_NOT_VERIFIED_PROTECTED':'AREA_DIVIDED_BY_ASSUMED_WIDTH',shore_length_sensitivity_m:direction.shore_length_sensitivity_m,bands,capital_recovery_factor:crf,economic_status:'ENGINEERING_FUNDING_COMPARISON_NOT_ECOSYSTEM_SERVICE_VALUE',avoided_damage_eur_per_year:null,ecosystem_service_value_eur:null,replacement_validity:{equivalent_service:false,least_cost:false,demand_demonstrated:false}};
}
root.ParametricCoast=Object.freeze({coefficient,calculate});
})(typeof window==='undefined'?globalThis:window);
