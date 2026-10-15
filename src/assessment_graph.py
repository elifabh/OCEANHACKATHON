"""Small, inspectable evidence graph and lexical index. No model or raw-data copies."""
import re

DOCS = [
 ('physics','Wave attenuation within the assumed cell','modelled',5,['dubi','infomar','cmems'], 'wave height attenuation percent 8.43 with without habitat depth coefficient direction H/H0', 'The deterministic engine applies laboratory damping to the selected directional chord. This is conditional attenuation inside an assumed habitat cell, never a shoreline hazard result.'),
 ('economics','Independent engineering funding comparison','assumed',7,['opw-cost'], 'euro cost money capital annual budget share frontage 562090 562,090 discount lifetime formula', 'Capital equals assumed frontage times published funding rate times independent budget share. Annualisation uses a capital recovery factor. Neither is avoided damage, savings or kelp value.'),
 ('history','Conflicting habitat reference lineage','historical',2,['npws','S5','obis'], 'historical kelp observations dates NPWS SSCO Article 17 faunal turf Laminaria independent conflict disagreement', 'Cape Clear references disagree: SSCO Laminaria community and Article 17 faunal turf at sample 1351. Shared legacy survey lineage prevents treating agreement as independent contemporary validation.'),
 ('extent','Present-day kelp extent needs a survey','unavailable',2,['npws','sentinel'], 'current kelp extent hectares species bed map confirmed today area', 'There is no confirmed current kelp boundary. The clipped sampling cell is a hypothetical model geometry, not a mapped current bed.'),
 ('assets','Coastal objects and unmodelled receptor hazard','unavailable',6,['osm','south-harbour-tender','cmems'], 'road building harbour protected protection shoreline safe flooding hazard house', 'Candidate road segments and building objects are geometric context, not verified protected properties. Offshore waves and straight rays do not resolve nearshore transformation or receptor hazard.'),
 ('damage','Evidence required for avoided damage','unavailable',7,['opw-cost','osm','cmems'], 'avoided damage savings benefit ecosystem service value worth financial profit', 'Avoided damage and ecosystem-service value are unquantified. Required: validated with/without receptor hazard, event probabilities, exposed asset values, damage functions and lifecycle costs.'),
 ('biodiversity','Geographic occurrence inventory','observed',8,['obis','biodiversity'], 'biodiversity taxa species records inventory filters rectangle richness score abundance', 'Provider records are filtered by the selected assessment rectangle, date, class, quality and search. Mixed taxa, heterogeneous effort and unverified kelp association prevent a kelp-bed biodiversity score.'),
 ('risk','Condition and decline-driver evidence','unavailable',4,['cmems','npws'], 'decline risk warming storm water quality habitat condition health trend loss', 'Wave exposure supplies context. Warming, light, disturbance and fragmentation are mechanisms to investigate; no Cape canopy trend or calibrated probability of decline is measured.'),
 ('priority','Research before restoration','historical',9,['npws','infomar','cmems'], 'next action research restore restoration priority survey monitoring permissions', 'Verify species and canopy with georeferenced underwater imagery, reconcile historical lineage, confirm the depth datum and observe nearshore waves. Establish degradation, pressures, substrate, permissions and recovery mechanism before restoration.'),
 ('satellite','Intertidal macroalgae is a separate target','modelled',2,['sentinel','S9','S13'], 'satellite classification machine learning random forest accuracy training validation Sherkin intertidal macroalgae', 'Sherkin optical and RF experiments remain frozen diagnostic comparisons, with land errors retained. They do not identify confirmed subtidal kelp or validate Cape Clear. No new model was trained.'),
 ('site','Why this assessment uses Cape Clear','historical',1,['npws','infomar','cmems','south-harbour-tender'], 'why Cape Clear main selected site strongest case comparison Copper Point Bantry Long Island', 'Cape Clear combines conflicting but traceable habitat evidence, a model-domain depth, directional wave data and real coastal engineering context. It supports a conditional prototype, not a demonstrated protection benefit. Copper Point experimental sonar/navigation/video were unavailable; Bantry has dated dives without bed geometry.'),
 ('sonar','Copper Point experimental access boundary','unavailable',2,['S1','S10','S14'], 'Copper Point sonar navigation water column footprint video 2019 available', 'The documented 2019 Copper Point experimental water-column sonar, navigation, survey footprint and video were not obtained. Generic bathymetry is not the canopy survey and its anchor depth is outside the damping domain.'),
 ('fisheries','Do not add fisheries value to funding','unavailable',7,['biodiversity','opw-cost'], 'fisheries crab lobster ecosystem add total millions monetary', 'Legacy fisheries examples cannot be added to an engineering funding comparator or transferred to Cape Clear. There is no local causal fishery-benefit valuation.'),
 ('method','How the local assistant works','modelled',11,[], 'assistant GraphRAG AI local model deterministic citations offline sources source evidence explain method', 'The assistant combines selected-state lookup, graph traversal and lexical text retrieval. Optional local Ollama selects an evidence document; a deterministic answer compiler supplies every scientific statement and number. It is not fine-tuned and uses no paid API.'),
]

def build_graph(product):
    nodes=[]; edges=[]; ids=set()
    def node(id,type,**data):
        if id not in ids: nodes.append(dict(id=id,type=type,**data));ids.add(id)
        return id
    def edge(a,r,b):edges.append(dict(source=a,relation=r,target=b))
    for s in product['sources']:node('source:'+s['id'],'Source',title=s['name'],url=s['url'])
    for n in range(1,13):node('report:'+str(n),'ReportSection',section=n)
    for i,title in enumerate(product['promise_sections'],1):
        node('promise:'+str(i),'ChallengePromise',title=title);edge('report:'+str([2,3,5,7,8,9,10][i-1]),'SATISFIES_PROMISE','promise:'+str(i))
    for i,title in enumerate(['Working demonstrator','Digital data','Ambition','Environmental and societal impact','Innovation','Team communication'],1):
        node('jury:'+str(i),'JuryCriterion',title=title);edge('report:11','EVIDENCES_CRITERION','jury:'+str(i))
    for key,c in product['cases'].items():
        sid=node('site:'+key,'Site',title=c['name']); aid=node('area:'+key,'AssessmentArea',bounds=c['bounds']);edge(sid,'LOCATED_IN',aid)
        hid=node('history:'+key,'HabitatEvidence',text=c['history_note'],result_type='historical');edge(hid,'LOCATED_IN',sid);edge(hid,'SUPPORTED_BY','source:npws');edge(hid,'DOES_NOT_VALIDATE',node('limit:current:'+key,'Limitation',text='No current bed extent'))
        if key=='cape_clear':
            node('npws:ssco','HabitatEvidence',title='SSCO Laminaria community');node('npws:article17','HabitatEvidence',title='Article 17 faunal turf');edge('npws:ssco','CONTRADICTS','npws:article17');edge('npws:ssco','DERIVED_FROM','source:npws');edge('npws:article17','DERIVED_FROM','source:npws');edge(hid,'SUPPORTED_BY','npws:ssco');edge(hid,'SUPPORTED_BY','npws:article17')
        for i,o in enumerate(c['observations']):
            oid=node(f'observation:{key}:{i}','Observation',record=o);edge(oid,'LOCATED_IN',sid);edge(oid,'DATED',node('date:'+str(o.get('eventDate')),'Date',value=o.get('eventDate')));edge(oid,'DERIVED_FROM','source:obis')
        inventory=node('inventory:'+key,'Dataset',count=c['biodiversity']['inventory_count'],pointer='product.cases.'+key+'.biodiversity.records');edge(inventory,'LOCATED_IN',aid);edge(inventory,'DERIVED_FROM','source:obis')
        # Main-case records are atomic graph nodes. Supporting inventories use
        # pointers into the existing payload, avoiding thousands of duplicate rows.
        for i,r in enumerate(c['biodiversity']['records'] if key=='cape_clear' else []):
            rid=node(f'bio:{key}:{i}','BiodiversityRecord',record_index=i);edge(rid,'LOCATED_IN',aid);edge(rid,'DERIVED_FROM',inventory);edge(rid,'DATED',node('date:'+str(r.get('eventDate')),'Date',value=r.get('eventDate')));edge(rid,'SUPPORTED_BY',node('taxon:'+str(r.get('scientificName')),'Taxon',name=r.get('scientificName')))
        for f in c['assets']['features']:
            aid2=node('asset:'+key+':'+str(f['properties'].get('osm_id')),'CoastalAsset',properties=f['properties']);edge(aid2,'LOCATED_IN',sid);edge(aid2,'DERIVED_FROM','source:osm')
        for p in c['priorities']:
            pid=node('priority:'+key+':'+p['id'],'ResearchPriority',title=p['title'],action=p['action']);edge(pid,'APPLIES_TO',sid)
        if c['scenario']:
            scenario=node('scenario:'+key,'WaveScenario',method=c['scenario']['method']);edge(scenario,'LOCATED_IN',sid);edge(scenario,'USES_ASSUMPTION',node('depth:'+key,'DepthInput',depth_m=c['scenario'].get('depth_m'),datum=c['scenario']['datum']));edge(scenario,'BOUNDED_BY',node('limit:depth','Limitation',text='Laboratory depth domain 4–10 m'))
            edge(scenario,'COMPUTED_FROM',node('geometry:'+key,'Geometry',pointer='product.cases.'+key+'.scenario_layer'))
            edge(node('output:'+key,'CalculationOutput',pointer='selected_state.assessment'),'COMPUTED_FROM',node('inputs:'+key,'CalculationInput',pointer='selected_state.inputs'))
            edge(node('economic:'+key,'EconomicScenario',pointer='selected_state.assessment.bands'),'USES_ASSUMPTION','inputs:'+key)
            for deg,d in c['scenario']['directions'].items():
                did=node('direction:'+key+':'+deg,'DirectionSector',from_deg=deg,open_upwave=d.get('open_upwave_5km'));edge(scenario,'COMPUTED_FROM',did)
    documents=[]
    for key,title,kind,section,sources,keywords,body in DOCS:
        id='doc:'+key;node(id,'Dataset',title=title,text=body,result_type=kind);edge(id,'SUMMARISED_IN','report:'+str(section))
        for s in sources:edge(id,'SUPPORTED_BY','source:'+s)
        if key=='history':edge(id,'SUPPORTED_BY','history:cape_clear')
        documents.append(dict(id=id,key=key,title=title,result_type=kind,section=section,source_ids=sources,text=body,keywords=keywords,tokens=re.findall(r'[a-z0-9]+',(title+' '+keywords+' '+body).lower())))
    return dict(schema='shield-graph-1',retrieval='BM25 text + graph neighbourhood + deterministic selected state',nodes=nodes,edges=edges,documents=documents)
