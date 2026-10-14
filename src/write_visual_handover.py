"""Write the short user handover and honest challenge/jury coverage record."""
from pathlib import Path
import shutil,json,hashlib
R=Path(__file__).resolve().parents[1];O=R/'outputs/presentations_visual_v2_20261014'
for name in ['TEAM_CONTRIBUTIONS.md','ORGANISER_DISCLOSURE_IP_DRAFT.md']:
    shutil.copy2(R/'outputs/presentations_final_20261014'/name,O/name)
shutil.copy2(R/'outputs/presentations_20261013/TEAM_ROLES_ONE_PAGE.md',O/'TEAM_ROLES_ONE_PAGE.md')
(O/'REHEARSAL_90_SECONDS.md').write_text('''# Ninety-second equipment rehearsal

0–15 seconds: double-click START_PRESENTATION.bat. Press F11. Choose the organiser's confirmed duration. The 3- and 5-minute options include the film.

15–30 seconds: choose Manual presentation. Use the right arrow twice. Point to green model cells, purple historical surveys and the blue intertidal proxy. Say: “These are different kinds of evidence.”

30–45 seconds: advance to the wave diagram. Wait three seconds for the comparison. Say: “This is conditional wave reduction inside assumed habitat. Asset protection is unproven.”

45–75 seconds: advance once and watch the entire 30-second film. It plays inside the same page. Check the euro slider, not-quantified caveat and downloadable report. No application switch is needed.

75–90 seconds: advance to the final scene if needed. Say: “The useful output is a shared brief for the next survey.” Press Escape. For the actual talk choose Start timed presentation and start your spoken notes immediately.

Space pauses or resumes. Left/right navigate. F11 controls full screen. Keep the whole folder together. Films are silent, with English captions. Do not speak over the film unless rehearsed. PowerPoint uses timed real recording frames; the HTML player uses continuous video.

## Pronunciation and plain words

Kelp: “kelp”, large brown seaweed. Roaringwater: “ROR-ing waw-ter”. Sherkin: “SHER-kin”. Kilkieran: “kil-KEER-an”. Kilkee: “kil-KEE”. Attenuation: “uh-ten-yoo-AY-shun”, wave reduction. Biodiversity: “bye-oh-dye-VER-si-tee”, variety of life. Laminaria hyperborea: “lam-ih-NAIR-ee-uh high-per-BOR-ee-uh”. You can say “kelp” in the talk and leave the Latin name in the notes.

## Before Sunday

Rehearse the complete chosen version aloud at your pace. These timings were tested as media, not as a recording of your voice. Fill TEAM_CONTRIBUTIONS.md with real weekend work and update the editable final slide. The speaking slot and organiser acceptance of pre-existing / AI-assisted work still need confirmation. The organiser draft is supplied but has not been sent.
''',encoding='utf8')
(O/'CHALLENGE_AND_JURY_CROSSWALK.md').write_text('''# Published challenge and jury evidence

Prepared 14 October 2026. A working screening prototype, with scientific validation limits. This file records what the user can actually do and where claims must stop.

| Published commitment | Working demonstration / takeaway | Scientific limit |
|---|---|---|
| Map Cork kelp habitat | Select three Sherkin model groups or the whole supported pilot. Toggle Sentinel-2 intertidal proxy, historical NPWS communities and modelled subtidal suitability. Export the selected map. | Satellite proxy does not identify subtidal L. hyperborea. Old NPWS reference is not a current survey. Model cells are not confirmed bed boundaries. |
| Habitat condition and decline risk | Inspect regional waterbody status, sparse SST snapshots and wave context; see the evidence required for a repeat survey. | No measured bed decline or calibrated decline probability. Context/proxies cannot replace repeated species and canopy observations. |
| Physical coastal protection | Run actual polygon/ray calculations with water level, direction and damping sensitivity. Compare with/without assumed habitat. | Laboratory depth/species transfer is conditional. No nearshore wave transformation, surge, inundation or validated benefit at receptors. |
| Parametric monetary assessment | Change a geometry-derived candidate shoreline length scenario, independent cost fraction, unit-cost multiplier, discount rate and lifetime. Export one-off and annualised capital comparisons. | Funding approvals are heterogeneous cost proxies. Equivalence, least cost and demonstrated demand are unproven. Actual avoided damage and ecosystem-service value remain unquantified. |
| Biodiversity | Inspect 14 of 17 regional reference taxa and sampling coverage. | Uneven observation effort; not local bed richness or 82% of biodiversity. Fisheries totals are a separate regional context, not coastal protection and not additive. |
| Restoration priorities | Download concrete field checks for species, density, substrate and paired wave measurements. Review Cork alternatives. | Legacy external false-positive rate 63.45% fails 30% criterion. Historical overlap does not repair validation. These are investigation priorities, not approved restoration sites. |
| Transferability | Reusable pipeline and documented evidence requirements. Galway/Clare context and separate transfer sections remain available. | Requires local calibration and validation. No claim of a complete euro assessment for all Irish sites. |
| Clickable map and usable output | Select area, inspect evidence, run scenarios, Generate Assessment Report, download self-contained HTML and Print / Save as PDF offline. | Supported pilot scale only; arbitrary coast selection cannot generate unobserved results. |

The Cork screen revisited 103 available building clusters, not every Cork coastal asset. Cape Clear has historical generic Laminaria evidence and 40 sampled depths in the laboratory range, but all 11 sampled groups have land-blocked incoming straight paths. Firkeel fails the depth range; inner Roaringwater has a species/exposure mismatch. No inspected alternative proves a habitat–wave–asset benefit chain. Sherkin is retained as a conditional physical demonstration.

| Judging criterion | Evidence in the app and presentation |
|---|---|
| Demonstrator | Scenes 3–6 and actual film show the complete selection-to-report workflow, including a downloaded output. |
| Digital data | Scene 3 and report distinguish Sentinel-2, NPWS, INFOMAR/EMODnet, CMEMS and OSM, with provenance and reproducible inputs. |
| Ambition | The workflow connects habitat evidence to coastal planning. The report identifies the missing validation needed for a future damage model. |
| Environmental and societal impact | Better targeted next surveys, visible uncertainty, and prevention of unsupported claims about protected assets. No measured conservation outcome is claimed. |
| Innovation | Geographic ray screening, model-domain checks and transparent economic assumptions in one offline workflow, with an auditable field brief. |
| Team communication and cohesion | Clear story, source register, proposed roles and editable contribution record. Actual weekend teamwork cannot be demonstrated before it occurs. |

Published challenge: https://www.campusmer.fr/all-challenges-ork02-seeing-the-invisible-shield-valuing-coastal-habitats-as-natural-infrastructure-4385-475-0-0.html

Do not call every scientific commitment validated. The prototype functionality is executable; ecological decline, actual avoided damage and restoration efficacy need additional evidence.
''',encoding='utf8')
(O/'KULLANIM_TR.html').write_text('''<!doctype html><html lang="tr"><meta charset="utf-8"><title>Ocean Hackathon — kısa kullanım</title><style>body{max-width:950px;margin:30px auto;padding:0 24px;color:#12313a;background:#f5f3e9;font:16px/1.45 "Segoe UI",sans-serif}h1{font:36px Georgia}h2{font-size:21px;margin:20px 0 6px}code{font-size:14px;overflow-wrap:anywhere}a{color:#226350}li{margin:4px 0}.limit{border-left:4px solid #b67e35;padding-left:14px} @page{size:A4;margin:14mm}@media print{body{margin:0;font-size:11px}h1{font-size:26px}h2{font-size:16px;margin-top:12px}code{font-size:10px}}</style>
<h1>Ocean Hackathon: aç, dene, sun</h1><p>14 Ekim 2026 · uygulama sürümü <b>d493f82c1a12</b> · Orijinal proje ve araştırma verileri yerinde.</p>
<h2>Uygulamayı aç</h2><p><code>C:\\Users\\Elif\\Desktop\\OCEANHACKATHON\\START_DEMO.bat</code> dosyasına çift tıkla. Açılan yerel sunucu penceresini demo boyunca açık tut. Yeniden üretmek için aynı klasörde <code>REBUILD_DEMO.bat</code>, test için <code>CHECK_DEMO.bat</code>. Uygulama: <code>outputs\\map\\index.html</code>.</p>
<p>Haritadan bir model grubunu seç → kanıt katmanlarını incele → koruma modelini çalıştır → maliyet varsayımlarını değiştir → <b>Generate Assessment Report</b>. <b>Download offline report</b> bağımsız HTML indirir. <b>Print / Save as PDF</b> ile A4, %100, üst/alt bilgiler kapalı seçerek PDF kaydet. Örnek: <a href="ASSESSMENT_GROUP_1.pdf">3 sayfalık Grup 1 raporu</a>.</p>
<h2>Cuma ve pazar sunumu</h2><p><code>C:\\Users\\Elif\\Desktop\\OCEANHACKATHON\\START_JURY_PRESENTATION.bat</code> dosyasına çift tıkla. Paket: <code>outputs\\presentations_visual_v2_20261014\\</code>. Taşırken bu klasörün tamamını birlikte taşı.</p>
<ul><li><b>Cuma:</b> “Friday invitation” ve <a href="FRIDAY_2_MINUTES.md">2 dakikalık İngilizce metin</a>. Düzenlenebilir <a href="FRIDAY_INVITATION.pptx">Cuma slaytı</a>.</li>
<li><b>Pazar:</b> 3 veya 5 dakikayı seç, “Start timed presentation”. Gerçek demo videosu aynı sayfada oynar; pencere değiştirme gerekmez. Süre, videoyu içerir. Resmî konuşma süresini organizatörle netleştir.</li>
<li><b>Tuşlar:</b> F11 tam ekran, boşluk duraklat/devam, oklar önceki/sonraki, Escape menü. “Manual presentation” elle ilerler. <a href="REHEARSAL_90_SECONDS.md">90 saniyelik prova</a>.</li>
<li>İngilizce tam metinler: <a href="SUNDAY_3_MINUTES.md">3 dakika</a>, <a href="SUNDAY_5_MINUTES.md">5 dakika</a>. <a href="JURY_Q_AND_A.md">15 jüri yanıtı</a>, <a href="NO_VIDEO_BACKUP.md">sözlü yedek</a>. Pazar katkı satırını yalnızca gerçekleşmiş takım çalışmasıyla doldur.</li></ul>
<p class="limit"><b>PowerPoint sınırı:</b> bu kurulumda gömülü film, kayıtlı dosya yeniden açılıp oynatma komutu verildiğinde ilerlemedi. Güvenilir ana yol çevrimdışı HTML sunumudur. PowerPoint’lerde gerçek kayıttan zamanlanmış kareler bulunur; sürekli video bulunduğu iddia edilmez. Düzenlenebilir pazar dosyaları <code>SUNDAY_3_MINUTES_FINAL_VERIFIED.pptx</code> ve <code>SUNDAY_5_MINUTES_FINAL_VERIFIED.pptx</code>.</p>
<h2>Ne gerçek, ne model?</h2><p>Grup 1 için koşullu model: dalga yüksekliği %8,56, enerji %16,03 azalır. Bu, varsayılan habitatın içindeki etkidir; kıyıda ölçülmüş koruma değildir. 239,62 m geometrik aday kıyı uzunluğu ve %100 bağımsız maliyet payında karşılaştırma €1.034.122–€1.713.425 tek seferlik; %4/50 yıl ile €48.139–€79.760/yıl yıllıklaştırılmış sermayedir. Bunlar önlenen hasar veya yıllık tasarruf değildir.</p>
<p class="limit"><b>Bilimsel olarak tamamlanamayan:</b> güncel yerel kelp yoğunluğu, ölçülmüş azalma, doğrulanmış habitat–dalga–varlık bağlantısı ve hasar fonksiyonları yok. Gerçek önlenmiş hasar ve kanıtlanmış ekosistem değeri <b>hesaplanamadı</b>; sıfır kabul edilmedi. Bölgesel 14/17 takson yerel tür zenginliği değildir. Restorasyon modeli dış doğrulamayı geçmedi (%63,45 yanlış pozitif). Balıkçılık ekonomik bağlamı ayrı bir hizmettir, koruma tutarına eklenmez.</p>
<h2>Takıma 60 saniyede anlat</h2><p>“Araç, ayrı kaynaklardaki kıyı verilerini tek bir inceleme akışında birleştiriyor. Bir alan seçip uydu sinyalini, eski habitat kayıtlarını ve model tahminlerini ayrı görebiliyoruz. Varsayımları değiştirerek dalga azalmasını ve koşullu mühendislik maliyetini yeniden hesaplıyoruz. Sonunda harita, kaynaklar, belirsizlikler ve sıradaki saha ölçümlerini içeren raporu alıyoruz. Bu, hangi kıyının nasıl araştırılacağına yardımcı oluyor. Bugün ne kadar hasar önlendiğini veya kelpin kesin ekonomik değerini ölçtüğümüzü söylemiyoruz.”</p>
<p><b>Kontroller:</b> <a href="DELIVERY_STATUS.json">gerçekte çalıştırılan testler ve durum</a>. Küçük kaynak yedeği: <code>outputs\\rollback_visual_v2_20261014\\</code>. Önceki sunumlar <code>outputs\\presentations_final_20261014\\</code> içinde korunuyor. <a href="VISUAL_ASSETS_AND_SOURCES.md">Kaynak/lisanslar</a> · <a href="CHALLENGE_AND_JURY_CROSSWALK.md">Challenge ve 6 kriter karşılığı</a>.</p></html>''',encoding='utf8')
print('Concise handover, rehearsal, contribution and coverage materials written')
