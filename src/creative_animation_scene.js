/* Requested scientific diagrams: source-based geographic camera and conceptual mechanisms. */
const canvas=document.querySelector('canvas'),g=canvas.getContext('2d'),W=1280,H=520;
const C={navy:'#082B3B',sea:'#123E50',land:'#AEC4BC',teal:'#5DD5C4',blue:'#8BCAFF',purple:'#D1B3F0',gold:'#F1C76B',white:'#F4F5EF',muted:'#BCD1D7'};
const clamp=x=>Math.max(0,Math.min(1,x)),ease=x=>{x=clamp(x);return x*x*(3-2*x)},lerp=(a,b,t)=>a+(b-a)*t;
const I={};window.ready=false;
Promise.all(Object.entries(IMAGE_URLS).map(([k,u])=>new Promise((ok,bad)=>{const im=new Image();im.onload=()=>{I[k]=im;ok()};im.onerror=bad;im.src=u}))).then(()=>window.ready=true);
function text(t,x,y,size=28,color=C.white,weight=500,align='left'){g.fillStyle=color;g.font=`${weight} ${size}px "Segoe UI",sans-serif`;g.textAlign=align;g.textBaseline='middle';g.fillText(t,x,y);}
function line(points,color=C.white,width=2,dash=[]){g.beginPath();points.forEach((p,i)=>i?g.lineTo(...p):g.moveTo(...p));g.strokeStyle=color;g.lineWidth=width;g.setLineDash(dash);g.stroke();g.setLineDash([]);}
function disk(x,y,r,color){g.beginPath();g.arc(x,y,r,0,Math.PI*2);g.fillStyle=color;g.fill();}
function bg(){g.clearRect(0,0,W,H);const grad=g.createLinearGradient(0,0,W,H);grad.addColorStop(0,'#103C4E');grad.addColorStop(1,'#041C2C');g.fillStyle=grad;g.fillRect(0,0,W,H);}
function reveal(t,start,duration,fn){const a=ease((t-start)/duration);if(a<=0)return;g.save();g.globalAlpha=a;fn(a);g.restore();}
function feature(fc,project,fill,stroke,width=1,alpha=1){g.save();g.globalAlpha=alpha;for(const f of fc.features||fc||[]){function draw(q){if(!q)return;if(q.type==='GeometryCollection'){q.geometries.forEach(draw);return}if(q.type==='Point'){const p=project(q.coordinates);disk(...p,4,stroke);return}const rings=q.type==='Polygon'?q.coordinates:q.type==='MultiPolygon'?q.coordinates.flat():q.type==='LineString'?[q.coordinates]:q.type==='MultiLineString'?q.coordinates:[];g.beginPath();for(const ring of rings){ring.forEach((ll,i)=>{const p=project(ll);i?g.lineTo(...p):g.moveTo(...p)});if(q.type.includes('Polygon'))g.closePath()}if(fill){g.fillStyle=fill;g.fill('evenodd')}if(stroke){g.strokeStyle=stroke;g.lineWidth=width;g.stroke()}}draw(f.geometry)}g.restore()}
function atlas(t){bg();
 const target=SOURCE.origin;let center=[-8.15,53.35],span=5.8;
 if(t>3){const q=ease((t-3)/6);center=[lerp(-8.15,-9.17,q),lerp(53.35,51.72,q)];span=Math.exp(lerp(Math.log(5.8),Math.log(1.6),q));}
 if(t>10){const q=ease((t-10)/7);center=[lerp(-9.17,-9.505,q),lerp(51.72,51.434,q)];span=Math.exp(lerp(Math.log(1.6),Math.log(.043),q));}
 const sc=450/span,cos=Math.cos(center[1]*Math.PI/180),project=ll=>[800+(ll[0]-center[0])*cos*sc,254-(ll[1]-center[1])*sc];
 const grid=span>2?1:span>.3?.2:.01;g.save();g.beginPath();g.rect(405,0,875,H);g.clip();
 for(let lon=Math.floor((center[0]-span*2)/grid)*grid;lon<center[0]+span*2;lon+=grid){const x=project([lon,center[1]])[0];line([[x,0],[x,H]],'#214555',1)}
 for(let lat=Math.floor((center[1]-span)/grid)*grid;lat<center[1]+span;lat+=grid){const y=project([center[0],lat])[1];line([[405,y],[1280,y]],'#214555',1)}
 feature(SOURCE.ireland,project,C.land,'#D4E3DA',1.1);
 if(span<.32){const a=clamp((.32-span)/.17);g.fillStyle=`rgba(8,43,59,${a})`;g.fillRect(405,0,875,H);feature(SOURCE.land,project,C.land,'#F0F4DA',1.5,a);}
 if(t>17)feature(SOURCE.history,project,'#785C96',C.purple,1.5,ease((t-17)/1.3));
 if(t>19){feature(SOURCE.assets,project,'#C3D0CE','#F4F5EF',1.7,ease((t-19)/1.2));for(const r of SOURCE.records){const pt=project([r.decimalLongitude,r.decimalLatitude]);disk(...pt,6,C.blue);}}
 if(t>21)feature(SOURCE.cell,project,'#B08630',C.gold,3,ease((t-21)/1.2));
 if(t>23){feature(SOURCE.paths,project,null,C.teal,3,ease((t-23)/1));const p=project(target);for(let i=0;i<3;i++){const q=((t*.25+i*.33)%1);line([[p[0]-75+q*60,p[1]+100-q*65],[p[0]-65+q*60,p[1]+105-q*65]],C.teal,3);}}
 const pt=project(target);disk(...pt,6,C.gold);g.beginPath();g.arc(...pt,15+4*Math.sin(t*2),0,6.283);g.strokeStyle=C.gold;g.lineWidth=2;g.stroke();
 if(span<.1){text('Cape Clear',project([-9.506,51.443])[0],project([-9.506,51.443])[1],29,C.navy,700);line([[pt[0]+12,pt[1]],[1068,pt[1]+45]],C.gold,2);text('South Harbour',1080,pt[1]+45,25,C.white,700);}
 else{const cork=project([-8.7,51.8]);text('CORK',cork[0]+18,cork[1]-24,28,C.white,700);}
 g.restore();
 const label=t<7?'IRELAND':t<14?'CORK':'CAPE CLEAR';text(label,55,57,30,C.teal,700);text(t<14?'Atlantic context':'South Harbour',55,109,43,C.white,650);
 const rows=[['Historical habitat',C.purple,17],['Dated records',C.blue,19],['Roads and buildings',C.white,19.8],['Assumed cell',C.gold,21],['Directional waves',C.teal,23]];
 rows.forEach(([s,col,start],i)=>{reveal(t,start,1,()=>{line([[58,190+i*51],[94,190+i*51]],col,5);text(s,109,190+i*51,27,col)});});
 if(t<17){text('One continuous map zoom',55,206,28,C.muted);text('Existing geographic sources',55,253,26,C.muted);}
 text('N ↑',1214,42,26,C.white,700);text(t<17?'Natural Earth orientation':'NPWS / OBIS / OSM / model geometry',430,489,24,C.muted);
}
function kelp(x,y,height,t,alpha=1){g.save();g.globalAlpha=alpha;const sway=Math.sin(t*1.45+x*.03)*13,crownY=y-height*.56,crownX=x+sway*.4;g.strokeStyle='#91A56A';g.lineWidth=3;g.beginPath();g.moveTo(x,y);g.bezierCurveTo(x-4,y-height*.2,crownX,crownY+15,crownX,crownY);g.stroke();
 // Stipe and blade crown, not terrestrial branches; generic kelp diagram.
 for(let j=0;j<5;j++){const direction=(j-2)*.45,tipX=crownX+height*direction*.6+sway,tipY=crownY-height*(.42-Math.abs(direction)*.1),bow=height*.14;g.beginPath();g.moveTo(crownX,crownY);g.bezierCurveTo(crownX+direction*height*.14-bow,crownY-height*.19,tipX-bow,tipY+height*.09,tipX,tipY);g.bezierCurveTo(tipX+bow*.7,tipY+height*.13,crownX+direction*height*.22+bow,crownY-height*.05,crownX,crownY);g.fillStyle=j%2?'#95A85B':'#BAC576';g.fill();}g.restore();}
function waveField(x,y,width,depth,t,ratio=1,plants=false){
 const top=y,back=depth*.36;g.save();
 // Bed and camera perspective are schematic, not bathymetric observations.
 const grd=g.createLinearGradient(x,y,x,y+depth);grd.addColorStop(0,'#257B91');grd.addColorStop(1,'#082A3A');
 g.fillStyle=grd;g.beginPath();g.moveTo(x+45,y);g.lineTo(x+width,y);g.lineTo(x+width-35,y+depth);g.lineTo(x,y+depth);g.closePath();g.fill();
 g.globalAlpha=.65;g.fillStyle='#778878';g.beginPath();g.moveTo(x+45,y+depth*.56);g.lineTo(x+width,y+depth*.56);g.lineTo(x+width-35,y+depth);g.lineTo(x,y+depth);g.closePath();g.fill();g.globalAlpha=1;
 if(plants)for(let j=0;j<3;j++)for(let k=0;k<7;k++)kelp(x+285+k*32-j*8,y+depth*.68+j*18,40+j*7,t+k*.2,.72);
 // Multiple moving crests form a surface, all attenuation amplitudes retain the engine ratio.
 for(let row=0;row<9;row++){const pts=[];for(let u=0;u<=width;u+=5){const progress=clamp((u-270)/220),amp=16*(1-(1-ratio)*progress);pts.push([x+u+45-row*5,y+row*7+Math.sin(u*.043-t*2.2)*amp]);}line(pts,row%2?'#8BCDE3':'#CAE9EE',row%3===0?2.4:1.1);}
 const left=x+310,right=x+530;line([[left,y-19],[left-36,y+depth],[right-36,y+depth],[right,y-19],[left,y-19]],C.gold,2.3,[8,5]);
 g.restore();
}
function mechanism(t){bg();const split=ease((t-4)/3),gap=ease((t-17)/4),scale=lerp(1.36,1,ease((t-1)/5));
 g.save();g.translate(40*(1-scale),35*(1-scale));g.scale(scale,scale);
 const width=lerp(1025,820,gap),top=lerp(110,60,split);
 text(split<.5?'Identical incoming conditions':'WITHOUT HABITAT',48,top-26,26,C.blue,700);waveField(40,top,width,142,t,1,false);
 if(split>0){g.globalAlpha=split;const y=lerp(110,282,split);text('WITH ASSUMED HABITAT',48,y-27,26,C.teal,700);waveField(40,y,width,142,t,SOURCE.result.with_relative_height,true);g.globalAlpha=1;}
 g.restore();
 reveal(t,8,1,()=>{text('H / H₀ = 1.000',1016-82*gap,141,25,C.blue,700,'center');text('H / H₀ = 0.916',1016-82*gap,362,25,C.teal,700,'center');});
 reveal(t,11,1,()=>{text('8.43%',667,235,50,C.teal,700);text('lower wave height within the cell',54,482,30,C.white,650);});
 reveal(t,17,2,()=>{const gx=1040;g.fillStyle='#253E4C';g.fillRect(gx,42,92,385);for(let yy=45;yy<430;yy+=20)line([[gx,yy],[gx+90,yy+40]],'#637783',1);text('?',gx+45,193,66,C.gold,600,'center');text('MODEL',gx+45,280,23,C.muted,600,'center');text('ENDS',gx+45,311,24,C.muted,700,'center');line([[1165,430],[1190,233],[1270,210]],'#B9C8BA',6);text('SHORE',1206,89,25,C.white,700,'center');text('Hazard',1206,127,23,C.muted,500,'center');text('unmodelled',1206,158,21,C.muted,500,'center');});
 text('ASSUMED CELL',355,226,22,C.gold,700);text('Conceptual section / normalized height / no shore prediction',54,513,21,C.muted);
}
function ecology(t){bg();const growth=ease((t-2)/5);const grad=g.createLinearGradient(0,0,0,H);grad.addColorStop(0,'#30798A');grad.addColorStop(.5,'#133F50');grad.addColorStop(1,'#061C2D');g.fillStyle=grad;g.fillRect(0,0,W,H);g.globalAlpha=.15;g.drawImage(I.kelp,0,0,W,H);g.globalAlpha=1;
 // Conceptual structural succession, never a time-series or restoration forecast.
 g.fillStyle='#52675C';g.beginPath();g.moveTo(0,455);for(let x=0;x<=1280;x+=25)g.lineTo(x,443+9*Math.sin(x*.027));g.lineTo(W,H);g.lineTo(0,H);g.fill();
 for(let j=0;j<3;j++)for(let k=0;k<10;k++){const x=230+k*67+j*19;kelp(x,470-j*18,(105+45*Math.sin(k*1.7+j))*growth,t+j*.6,.45+j*.2)}
 const groups=[['Fish','fish',200,130,8],['Juvenile stages','fish',1000,200,10],['Invertebrates','crab',225,365,12],['Shellfish','shell',1010,400,14]];
 groups.forEach(([label,key,x,y,start],i)=>reveal(t,start,1.3,a=>{const drift=Math.sin(t*.8+i)*10;const size=i===1?76:107;g.drawImage(I[key],x-size/2+drift,y-size/2,size,size);text(label,x,y+69,29,C.white,600,'center');const q=ease((t-start-1)/2);line([[x+(x<640?70:-70),y],[lerp(x+(x<640?70:-70),640,q),lerp(y,330,q)]],C.teal,2,[7,6]);}));
 text(t<4?'REEF STRUCTURE':t<8?'KELP STRUCTURE':'HABITAT RELATIONSHIPS',50,42,28,C.white,700);
 reveal(t,16,1,()=>{text('Refuge',590,98,34,C.white,650);text('Feeding',700,174,34,C.white,650);text('Macroalgal structure',640,467,28,C.teal,700,'center');});
 text('Conceptual ecology / no local abundance or fisheries estimate',50,510,23,C.muted);
}
function monitoring(t){bg();
 text('POTENTIAL PRESSURES',45,37,27,C.muted,700);
 const pressure=[['thermometer','Warming',70],['wave','Storms',240],['microscope','Water quality',410]];
 pressure.forEach(([key,label,x],i)=>{g.drawImage(I[key],x,76+Math.sin(t*1.3+i)*4,75,75);text(label,x+37,182,26,C.white,600,'center')});
 text('Disturbance / fragmentation / monitoring gaps',47,231,25,C.muted);
 line([[530,152],[594,152],[580,141],[594,152],[580,163]],C.teal,3);
 const baseline=ease((t-3)/3),repeat=ease((t-9)/4);
 for(let i=0;i<2;i++){
  const x=620+i*318,y=70,w=280,h=220;g.save();g.globalAlpha=i?repeat:baseline;
  g.drawImage(I.kelp,x,y,w,h);g.fillStyle='rgba(8,43,59,.3)';g.fillRect(x,y,w,h);
  g.strokeStyle=C.gold;g.lineWidth=3;g.strokeRect(x+32,y+27,210,165);
  for(let j=1;j<4;j++){line([[x+32+j*52.5,y+27],[x+32+j*52.5,y+192]],C.gold,1);line([[x+32,y+27+j*41.25],[x+242,y+27+j*41.25]],C.gold,1)}
  const scan=((t+(i?1:0))%4)/4;line([[x+32,y+27+165*scan],[x+242,y+27+165*scan]],C.teal,4);
  text(i?'REPEAT SURVEY':'BASELINE SURVEY',x,y+258,27,C.white,700);g.restore();
 }
 reveal(t,14,2,()=>{text('Same footprint',636,363,30,C.teal,650);text('Same method and season',636,408,30,C.teal,650)});
 reveal(t,18,1,()=>{text('Verify the bed',48,332,36,C.white,650);text('Measure comparable change',48,385,32,C.white,650);text('Then test restoration eligibility',48,438,31,C.teal,700)});
 text('Proposed monitoring design / illustrative imagery / no survey results or measured decline',47,502,24,C.muted);
}
let integratedMap;
function comparison(t){
 if(!integratedMap){atlas(27);integratedMap=document.createElement('canvas');integratedMap.width=W;integratedMap.height=H;integratedMap.getContext('2d').drawImage(canvas,0,0);}
 bg();
 const items=[['Historical polygons',C.purple],['Dated observations',C.blue],['Satellite evidence',C.teal],['Waves and depth',C.blue],['Coastal objects',C.muted]];
 text('SEPARATE SOURCES',50,27,27,C.muted,700);
 text('ONE ASSESSMENT',620,27,27,C.teal,700);
 g.drawImage(integratedMap,594,53,650,264);
 line([[412,240],[565,240],[550,230],[565,240],[550,250]],C.teal,4);
 items.forEach(([label,col],i)=>{
  const progress=ease((t-5-i*2)/5),x=lerp(48,617,progress),y=lerp(72+i*78,326+i*29,progress),scale=lerp(1,.69,progress);
  g.save();g.translate(x,y);g.scale(scale,scale);g.fillStyle='#163F50';g.fillRect(0,0,344,59);g.fillStyle=col;g.fillRect(0,0,7,59);text(label,25,29,28,C.white,600);g.restore();
 });
 if(t>18){const progress=ease((t-18)/3);g.save();g.translate(-380*(1-progress),0);text('Connected,',50,198,43,C.white,700);text('with evidence',50,254,43,C.white,700);text('kept distinct.',50,310,43,C.teal,700);g.restore();}
 text('Existing mapping retained / historical, observed, modelled and assumed sources remain distinct',47,506,23,C.muted);
}
window.render=(name,t)=>({atlas,mechanism,ecology,monitoring,comparison}[name])(t);
