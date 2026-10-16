"""Materialise delivery documentation from the verified final case and source register."""
from pathlib import Path
import json, shutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/final_overnight_20261015'
D=json.loads((OUT/'app/evidence.json').read_text(encoding='utf-8'))
C=json.loads((ROOT/'work/final_overnight/deck-contract.json').read_text(encoding='utf-8'))
assert D['build_id']==C['build_id']=='6a84de90fe69'
B=C['build_id']; R=C['canonical_result']
shutil.copyfile(ROOT/'work/final_overnight/deck-contract.json',OUT/'presentation_contract.json')
shutil.copyfile(ROOT/'src/assistant_config.json',OUT/'assistant_config.json')
def write(name,body):
    (OUT/name).write_text(body.strip()+'\n',encoding='utf-8')
for p in (ROOT/'src/final_narration').glob('*.md'):
    shutil.copyfile(p,OUT/p.name)

write('HARDWARE_AND_LOCAL_AI_REPORT.md',f'''# Hardware and local assistant

Build `{B}`. Machine audit: `qa/hardware.json`; raw benchmark: `qa/local_model_benchmark.json`; integrated runtime checks: `qa/assistant-service.json`.

| Item | Observed result |
|---|---|
| CPU | Intel Core i7-11800H, 8 cores / 16 threads |
| RAM | 16,909,434,880 bytes, approximately 15.75 GiB |
| GPU | NVIDIA GeForce RTX 3060 Laptop GPU, 6,144 MiB VRAM; use nvidia-smi, not the truncated CIM AdapterRAM field |
| Available GPU memory at audit | 5,500 MiB before model loading; 3,522 MiB in the later sample |
| Disk C | 498,496,172,032 bytes total; 21,669,203,968 free at initial audit |
| Windows | Windows 11 Education, build 10.0.26200 |
| PowerPoint | Version 16.0, native COM automation and slideshow playback tested |
| Ollama | 0.40.4, already installed |
| Chosen model | Existing gemma2:2b, 2.6B parameters, Q4_0, approximately 1.6 GB on disk |
| Model download | Zero bytes; qwen2.5:3b was absent, so the smaller installed candidate was used |
| Measured model allocation | 1,812,264,386 bytes on GPU at context length 2,048 |
| Embedding | Installed nomic-embed-text tested: 768 dimensions, two vectors in 25.39 seconds cold; not required in production |

## Benchmark interpretation

The first cold Gemma routing request exceeded the 45-second exploratory timeout. A following request took 8.13 seconds. Three ordinary warmed routing requests took 0.248, 0.289 and 0.284 seconds. The unguarded model routed a request to invent positive savings into the economics topic. It therefore **does not pass as an independent scientific answer generator**.

Production uses the model only to select an evidence topic. The deterministic compiler enforces refusal, citations and exact engine numbers. The 8-second server timeout and 10-second browser timeout leave the already-displayed deterministic answer intact. The real local service and controlled unavailable/slow-model cases are tested separately. Timings are samples from this machine, not service-level guarantees or an exhaustive comparison of all installed models.

No claim of fine-tuning, local model training, or general model safety is made. Controlled English answer templates provide readable answers. No model-authored free-text scientific result is displayed.

## Three retrieval layers

1. Selected case, inputs, filters and deterministic engine output.
2. Two-hop traversal of a typed JSON knowledge graph, including source lineage and contradictions.
3. BM25 text retrieval over 14 registered evidence documents.

This text-plus-graph hybrid requires no vector database or second resident model. `app/assistant_graph.json` and the graph embedded in `app/evidence.json` retain the local corpus. No paid API is configured. The optional service binds only to loopback, validates Host and Origin, requires a session token and restricts the executable entry point. Questions cannot choose paths or execute code.

## Operation

`START_DEMO.bat` opens the offline file application with deterministic retrieval only. `START_ASSISTANT.bat` starts the optional loopback service and opens its browser page. Uncheck **Use local model to interpret questions** to disable model routing immediately. Recheck to enable it while Ollama is available. Closing the panel does not stop the assessment. If Ollama is unavailable, use the same question panel in evidence mode.

Run `CHECK_DEMO.bat` for the reproducible product checks. Source entry points: `assessment_graph.py`, `assessment_assistant.js`, `assistant_server.py`, `assistant_cli.cjs`, `assistant_panel.js`, and `assistant_config.json` under `src/`.
''')

promises=[
('Habitat mapping','Historical layers, dated-record filters, reference disagreement, separate optical proxy and suitability','NPWS / OBIS / Sentinel-2; inherited survey lineage retained','Spatial selection, no new classifier training','Stages 1–2; map layers','§2','3–5','Frozen mapping tests; browser history/layer tests','Current subtidal kelp extent and independent contemporary validation unavailable.'),
('Condition and decline risk','Exposure chart, condition components and pressure evidence views','2015–2024 CMEMS offshore wave series; explicit local data gaps','Annual wave summaries and evidence categories, no health score','Stage 2: Condition / Decline drivers','§3–4','4, 9','Wave/source regression; condition and risk browser views','No measured canopy trend, bed-level temperature/clarity or calibrated decline probability.'),
('Coastal protection','Directional paths, with/without cell result, depth sensitivity, pinned comparison, asset inspection','Historical assumed cell, AllSurvey depth, CMEMS directions, OSM','H/H0 = exp(−sum kL), valid depth domain 4–10 m','Stage 3','§5–6, 10','5–6','46 numerical tests include 864 geometry/kernel combinations; browser scenarios','Datum and habitat unverified; no nearshore hazard or protected-property result.'),
('Euro value','Low/pooled/high capital and annual-equivalent scenario with independent controls','Published OPW funding approvals and declared frontage/share','Length × funding €/m × independent share; capital recovery factor','Stage 4','§7','7','Numerical boundary tests, zero discount and share independence; current assistant numbers','Engineering funding comparator only; avoided damage and kelp service value remain null.'),
('Biodiversity score','Taxon/date/quality/search filters, counts, map, record export','154 Cape geographic records, 109 taxon names at default','Deduplicated geographic inventory and taxonomic composition','Stage 5','§8','8','Frozen inventory tests; filtered report and assistant tests','Promise preserved as an explicit partial capability. No effort-standardised kelp-bed score or fisheries value.'),
('Research/restoration priorities','Selectable investigations, map context, required expertise and eligibility gate','Source disagreement, current evidence gaps and candidate physical pathway','Transparent action rules, no invented restoration ranking','Stage 5','§9','9–10','Priority selection/map/export browser checks','No measured degradation, approved restoration site or predicted recovery benefit.'),
('Transferable tool','Four case schemas, portable state/report, offline workflow and guarded assistant','Cape Clear main; Sherkin, Copper Point, Bantry supporting','Shared contracts; calculations only where case inputs support them','Case selector; stages 1–6; Ask panel','§10–12','3–4, 10–11','Supporting-case tests; desktop/mobile/projector; Chrome/Edge; report round trip','New locations and habitats require local evidence, physical calibration and validation.')]
head='| Published promise | Working feature | Evidence/data | Calculation | App | Report | Slides | Test evidence | Scientific limit |\n|---|---|---|---|---|---|---|---|---|\n'
write('PROMISE_MATRIX_FINAL.md',f'# Seven published promises\n\nBuild `{B}`. Working features do not convert partial scientific support into validated ecological outcomes.\n\n'+head+'\n'.join('| '+' | '.join(p)+' |' for p in promises))
jury=[
('Working demonstrator','Six stages, maps, stateful assistant and downloadable visual report','Frozen local case and source snapshots','Deterministic scenario/state contracts','All stages','§1–12','10; real video','159 product checks/groups plus deck/media acceptance','Demonstration is conditional, not an approved engineering design.'),
('Digital data','Joint geographic inspection with provenance and quality flags','NPWS, OBIS, Sentinel-2, CMEMS, INFOMAR, OSM','Reprojection, spatial joins, quality flags, typed graph','Maps/history/assistant','§2, 6, 8, 12','3–5','Source-input-output hashes, graph/citation checks','Shared source lineage is not independent validation.'),
('Ambition','Habitat-to-wave-to-assets-to-funding assessment with explicit missing links','Case geometry, depth, waves, assets, funding sources','Cell response plus separate funding comparator','Stages 2–4','§2–7','3–7','Domain, state-change and unsupported-benefit tests','Nearshore/receptor/avoided-damage chain is not yet calculated.'),
('Environmental and societal impact','Research priorities tied to a real coastal engineering context','South Harbour tender; habitat and inventory evidence','Evidence-led action gates, no fabricated benefit total','Stages 2, 5','§4, 6, 9','2, 5, 8–9, 12','Priority/map tests and scientific claim guards','Impact is prospective usefulness, not a measured environmental or financial improvement.'),
('Innovation','State + graph + text retrieval with optional local model and verified answers','Typed provenance graph and current application state','BM25 + two-hop traversal + engine, no LLM arithmetic','Ask panel and scenarios','§10–12','4, 11','48 assistant checks plus 14 service checks and 10 browser groups','No fine-tuning; optional model routing alone is not trusted.'),
('Team cohesion and communication','Editable contribution fields, role-specific actions and portable artifacts','Documented ecology, engineering, economics and GIS evidence needs','Shared case/state/report contracts','Stage 5 actions; report','§9, 11','11; separate English scripts','Artifacts and handover checked; actual team contributions left editable','Software cannot establish teamwork or invent future weekend contributions.')]
write('JURY_MATRIX_FINAL.md',f'# Six jury criteria\n\nBuild `{B}`. Criteria are linked to visible evidence, not self-awarded scores.\n\n'+head.replace('Published promise','Criterion')+'\n'.join('| '+' | '.join(p)+' |' for p in jury))

numbers=[
('Default within-cell wave-height reduction',f"{R['height_fraction']*100:.8f}% → 8.43%",'Modelled, unvalidated','ParametricCoast; FROM 210°, default interpolated laboratory coefficients','Not shore wave height, flood reduction or asset protection.'),
('Default cell area',f"{R['area_m2']:.8f} m²",'Assumed geometry','Historical clipped cell used for calculation','Not confirmed current kelp extent.'),
('Default ray length',f"{R['path_m_mean']:.8f} m",'Geometric screening','Selected scenario central ray','Not a calibrated refracted wave path.'),
('Depth sensitivity +2 m','Approximately 3.56% height attenuation','Modelled sensitivity','Same direction, engine at added 2 m','Not a tide or sea-level forecast; original vertical datum unverified.'),
('Comparison frontage','100 m','Independent assumption','User input; slide line is an illustrative 100 m coast segment','Not protected frontage or tender alignment.'),
('Budget share','100%','Independent assumption','User input, separate from wave-height attenuation','Not a habitat contribution estimate.'),
('Annualisation','4% / 50 years','Assumed finance parameters','Capital recovery factor; at zero discount use 1/n','Not annual savings; maintenance/restoration costs omitted.'),
('Cape inventory','154 records / 109 distinct taxon names','Provider-reported, dated geographic records','Default unfiltered assessment rectangle','Mixed taxa and heterogeneous effort; not kelp-bed richness.'),
('200°/210° offshore opportunity','6.817% of H²Tm proxy','Directional screening','Two offshore directional bins','Not intercepted wave energy or annual protection benefit.'),
('Candidate low-DSM objects','4 road segments + 3 building objects','Spatial diagnostics','Saved combined 200°/210° screening','Not distinct properties, protected objects or validated flood exposure.'),
('Unsupported values','Current bed extent / measured decline / shoreline hazard / avoided damage / kelp service value = null','Unavailable','Explicit app and report contract','Never substitute a historical polygon, score, funding amount or regional literature value.'),
]
for band,v in R['bands'].items():
    numbers.append((band+' funding band',f"€{v['capital_eur']:,.8f} capital; €{v['annualised_eur_per_year']:,.8f}/year annual equivalent",'Engineering funding comparator',f"€{v['unit_eur_per_m']:,.8f}/m × 100 m × 100%; annualisation 4%, 50 years",'Not kelp value, verified construction price or avoided damage.'))
write('NUMBERS_AND_CLAIMS_REGISTER.md',f'''# Numbers and claims register

Build `{B}`. Values below are taken from `work/final_overnight/deck-contract.json`, whose results come from the same deterministic application engine. UI and slides round for readability. Full precision is retained in JSON. The report generated during the video is a selected-state export and may retain the visibly demonstrated A/B pin, map layers and investigation focus.

| Quantity | Value | Type | Basis | Boundary |
|---|---|---|---|---|
'''+ '\n'.join('| '+' | '.join(p)+' |' for p in numbers)+'''

The three funding source inputs are €668,921 / 155 m, €657,338 / 100 m and €500,535 / 70 m. The pooled rate is their summed funding divided by 325 m. These are mixed nominal 2024/2026 approved funding, not inflation-adjusted quotes for Cape Clear.

The physical reference is Dubi & Tørum (1996), laboratory coefficients 0.0094, 0.0032, 0.0014, 0.0005 m⁻¹ at 4, 6, 8, 10 m. Assumed 2 m plants and 12 plants/m² are not local measurements. The validity gate rejects out-of-domain depth. The assistant cannot change these source values or create new outputs.
''')

credits=json.loads((ROOT/'src/assets/story/credits.json').read_text(encoding='utf-8'))
text=f'# Source and image attribution\n\nBuild `{B}`. Original files remain in place. This delivery reuses small processed assets and references original data without copying raw datasets.\n\n## Presentation images\n\n'
for x in credits:
    if x['file'] not in ['kelp-forest.jpg','sherkin-coast.jpg']:continue
    text+=f"### {x['file']}\n\n{x['author']}. [{x.get('caption',x['file'])}]({x['source']}). [{x['licence']}]({x.get('terms',x['source'])}). Changes: {x.get('changes','Display crop only')}.\n\n"
    text+=('Used on slides 1, 2, 8 and 12 as background ecological context. Molène, France; not a Cape Clear observation.\n\n' if x['file']=='kelp-forest.jpg' else 'Used on slide 1 as Irish coast context. Sherkin, 18 July 2009; not Cape Clear.\n\n')
text+='Ireland outline: Natural Earth public-domain geographic context. Cape Clear maps: processed NPWS / OSM / OBIS and saved scenario geometry, with attribution retained below. Slide 7 line is a computed illustrative 100 m coast segment, not a tender or protected frontage. Product poster and both movies are direct captures of the final application. No generated underwater evidence or synthetic application screens are used.\n\n## Data and research register\n\n'
for s in D['product']['sources']:
    text+=f"### {s['id']} — {s['name']}\n\n[{s['name']}]({s['url']})\n\nRole: {s.get('role','Reference')}. Dates: {s.get('dates','See provider')}. Attribution: {s.get('attribution',s['name'])}. Terms: {s.get('licence','Original provider terms')}.\n\nBoundary: {s.get('limits','See source metadata')}.\n\n"
text+='## Software and animations\n\nLeaflet 1.9.4 is bundled with its BSD-2-Clause licence. GraphRAG uses local JSON/BM25 and optional Ollama. PowerPoint-native fade, wipe, fly and zoom effects are edited through the installed PowerPoint object model. The scientific waves are explanatory animation of the conditional cell model, not measured wave footage. Native charts retain editable numerical data. No paid API is used.\n'
write('SOURCE_ATTRIBUTION.md',text)

write('KULLANIM_TR.md',f'''# Invisible Shield — kullanım ve teslim

Uygulama yapı kimliği: `{B}`. Son Git commit ve test sonuçları: `FINAL_ACCEPTANCE.json`.

## Çift tıklayarak aç

- Çevrimdışı ana ürün: `C:\\Users\\Elif\\Desktop\\OCEANHACKATHON\\START_DEMO.bat`
- İsteğe bağlı yerel model: `C:\\Users\\Elif\\Desktop\\OCEANHACKATHON\\START_ASSISTANT.bat`
- Doğrudan çevrimdışı dosya: `C:\\Users\\Elif\\Desktop\\OCEANHACKATHON\\outputs\\final_overnight_20261015\\app\\index.html`
- Sunum: aynı teslim klasöründe `INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pptx`
- Otomatik ayrı video geçişli gösterim: `C:\\Users\\Elif\\Desktop\\OCEANHACKATHON\\START_JURY_SHOW.bat`

Tüm son teslimler `C:\\Users\\Elif\\Desktop\\OCEANHACKATHON\\outputs\\final_overnight_20261015` içinde. Önceki kabul edilen uygulama `outputs/map` altında korunur.

## Uygulama akışı

1. Cape Clear / South Harbour seçili açılır. Haritadaki katmanları ve kaynak açıklamalarını inceleyin.
2. Habitat & condition bölümünde tarih, koşul ve baskı görünümlerini kullanın. Tarihsel kayıt güncel yatak haritası değildir.
3. Coastal protection bölümünde yön ve derinlik duyarlılığını değiştirin. A senaryosunu sabitleyerek karşılaştırın.
4. Euro scenarios bölümünde uzunluk, bütçe payı, iskonto ve süreyi değiştirin. Bu tutar mühendislik finansmanı karşılaştırmasıdır.
5. Biodiversity & action bölümünde kayıtları filtreleyin ve araştırma önceliğini haritada bulun.
6. Assessment report ile seçili durumdan HTML, JSON ve tarayıcı yazdırmasıyla PDF alın.

Ask the Assessment paneli çevrimdışı kanıt yanıtları verir. Yerel model başlatıcısında **Use local model to interpret questions** kutusu modeli açar/kapatır. Model kapalı veya erişilemezken ana ürün ve yanıtın deterministik sürümü çalışır. Sayıları model hesaplamaz.

## Dosyalar

- `ASSESSMENT_CAPE_CLEAR.html`, `.pdf`, `.json`: varsayılan örnek rapor. HTML'de bölüm seçimi ve kayıt araması çalışır.
- `qa/ASSESSMENT_MODIFIED.*`: değiştirilmiş girdi/filtrelerin rapora geçtiği test örneği.
- `app/assistant_graph.json`: yerel bilgi grafı ve metin indeksi; `assistant_config.json`: model ayarları.
- `SUNDAY_10_MIN_SCRIPT.md`: ayrı İngilizce konuşma metni. PowerPoint konuşmacı notları boş.
- `VIDEO_LIVE_NARRATION.md`: sessiz videolar üzerinde canlı anlatım.
- `Q_AND_A_20.md`: 20 jüri sorusu ve sınırları belirtilmiş yanıtlar.
- `DEMO_75_SECONDS.mp4`, `DEMO_30_SECONDS.mp4`: son kaydedilen gerçek ürün videoları.
- `PRESENTATION_MONTAGE.png`, `INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pdf`: görsel sunum inceleme çıktıları.
- `PROMISE_MATRIX_FINAL.md`, `JURY_MATRIX_FINAL.md`, `NUMBERS_AND_CLAIMS_REGISTER.md`, `SOURCE_ATTRIBUTION.md`: taahhüt, ölçüt, sayı ve kaynak kayıtları.
- `HARDWARE_AND_LOCAL_AI_REPORT.md`, `FINAL_ACCEPTANCE.json`, `qa/`: donanım ve gerçek test kanıtları.

## Sunum ve video

12 slaytın konuşma süreleri toplam 525 saniyedir. Slayt 10'un 35 saniyelik anlatımından sonra 75 saniyelik video gelir; planlanan toplam 600 saniyedir. PowerPoint geçişleri ve pencere açılışı birkaç saniye ekleyebilir; gerçek ölçüm `FINAL_ACCEPTANCE.json` içindedir. 30 saniyelik film kısa yedektir. Otomatik ayrı oynatma / elle ekleme durumu ve kesin yönergeler `MANUAL_VIDEO_INSERTION.md` dosyasındadır. Yazılım oynatma kontrolü insan konuşma provası yerine geçmez. MP4 gömme doğrulanmadığı için final sunumda poster bulunur. Doğrudan Chrome kaydında işletim sistemi işaretçisi görünmez; gerçek kontrol odağı ve etkileşimler görünür.

## Bilimsel sınır

Güncel kelp alanı, ölçülmüş habitat kaybı, kıyı tehlikesindeki azalma, korunduğu doğrulanmış bina/yol ve önlenen zarar hesaplanmış değildir. Varsayılan 8,43% hücre içi koşullu modeldir. Yaklaşık €562.090 bağımsız finansman karşılaştırmasıdır. 154 kayıt / 109 takson adı coğrafi envanterdir; kelp yatağı biyolojik çeşitlilik skoru değildir.

## Yeniden üretim

`CHECK_DEMO.bat` ürün testlerini tekrar çalıştırır. `REBUILD_DEMO.bat` yeni uygulama çıktısını kaynaklardan üretir; bir kaynak değişikliği yapı kimliğini değiştirebilir. Kaynak değiştirildiğinde sunum/video senkronizasyonu yeniden yapılmalıdır. Önceki veriler, donmuş testler ve kabul edilen uygulama çıktısı bu işlemde değiştirilmez.
''')
print(json.dumps({'build_id':B,'status':'WRITTEN','narration_and_playback_files':len(list((ROOT/'src/final_narration').glob('*.md'))),'matrices':2,'other_docs':4}))
