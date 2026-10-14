"""Generate release instructions from the same computed scenario as the films/decks."""
from pathlib import Path
import json,shutil,html
R=Path(__file__).resolve().parents[1];O=R/'outputs/jury_release_20261014'
e=json.loads((O/'PRESENTATION_SCENARIO.json').read_text(encoding='utf8'));r=e['result']
money=lambda n:f'€{round(n):,}'.replace(',','.')
capital='–'.join(money(r['bands'][x]['capital_eur']) for x in ['low','high'])
annual='–'.join(money(r['bands'][x]['annualised_eur_per_year']) for x in ['low','high'])
for name in ['TEAM_CONTRIBUTIONS.md','ORGANISER_DISCLOSURE_IP_DRAFT.md','TEAM_ROLES_ONE_PAGE.md','REHEARSAL_90_SECONDS.md','CHALLENGE_AND_JURY_CROSSWALK.md']:
 shutil.copy2(R/'outputs/presentations_visual_v2_20261014'/name,O/name)
rehearsal=O/'REHEARSAL_90_SECONDS.md'
rehearsal.write_text(rehearsal.read_text(encoding='utf8').replace('Films are silent, with English captions. Do not speak over the film unless rehearsed.','Films have no audio, subtitles or added overlays. Speak over the film using the timed English narration in the slide notes.'),encoding='utf8')
body=fr'''<!doctype html><html lang="tr"><meta charset="utf-8"><title>Ocean Hackathon — güncel teslim</title>
<style>body{{max-width:920px;margin:30px auto;padding:0 24px;color:#12313a;background:#f5f3e9;font:16px/1.45 "Segoe UI",sans-serif}}h1{{font:34px Georgia}}h2{{font-size:21px;margin:18px 0 6px}}code{{font-size:14px;overflow-wrap:anywhere}}a{{color:#226350}}li{{margin:4px 0}}.limit{{border-left:4px solid #b67e35;padding-left:14px}}@page{{size:A4;margin:14mm}}@media print{{body{{margin:0;font-size:11px}}h1{{font-size:26px}}h2{{font-size:16px}}code{{font-size:10px}}}}</style>
<h1>Ocean Hackathon: güncel, tutarlı sunum paketi</h1>
<p>14 Ekim 2026 · uygulama <b>{e['build_id']}</b> · senaryo <b>{e['id']}</b></p>
<h2>Çift tıklayarak aç</h2>
<p>Uygulama: <code>{R}\START_DEMO.bat</code><br>Jüri sunumu: <code>{R}\START_JURY_PRESENTATION.bat</code><br>Güncel paket: <code>{O}</code></p>
<p>Uygulamanın yerel sunucu penceresini açık tut. Jüri sunumu, internet veya sunucu olmadan çalışır. Klasörün tamamını birlikte taşı.</p>
<h2>Tekrarlanabilir sunum senaryosu</h2>
<p>Varsayılan <b>yedi hücrelik pilot alanı / 1,75 ha</b> kullan. Yön farkı 0°, su seviyesi +0 m, katsayı interpolasyonu ×1, geometrik aday kıyı yöntemi, bağımsız maliyet payı %100, birim fiyat çarpanı 1, iskonto %4 ve süre 50 yıl. 100 m genişlik bu yöntemde etkin değildir. Filmler varsayımları geçici değiştirir ve rapor indirmeden önce bu başlangıç değerlerine döner.</p>
<p>Geometrik aday kıyı {r['comparison_length_m']:.2f} m. Koşullu model: dalga yüksekliği %{r['height_fraction']*100:.2f}, enerji %{r['energy_fraction']*100:.2f}. Sermaye karşılaştırması <b>{capital}</b>; yıllıklaştırılmış sermaye <b>{annual}/yıl</b>. <b>Önlenmiş hasar, yıllık tasarruf veya doğrulanmış ekosistem değeri değildir.</b> Aralık farklı yayımlanmış mühendislik fonlama oranlarına dayanır; istatistiksel güven aralığı değildir.</p>
<h2>Raporu al</h2>
<p>Alan seç → kanıtları incele → koruma/maliyet varsayımlarını çalıştır → <b>Generate Assessment Report</b>. <b>Download HTML report</b> bağımsız HTML indirir. <b>Print / Save as PDF</b> ile A4, %100 ölçek, üst/alt bilgiler kapalı seçerek PDF kaydet. Tek tık doğrudan PDF indirme özelliği yoktur. Aynı senaryodan üretilmiş örnek: <a href="ASSESSMENT_PILOT.pdf">3 sayfalık PDF</a> / <a href="ASSESSMENT_PILOT.html">çevrimdışı HTML</a>.</p>
<h2>Cuma ve pazar</h2>
<p>Menüde “Friday invitation” / <a href="FRIDAY_2_MINUTES.md">2 dakikalık metin</a>. Pazar için 3 veya 5 dakika seçip “Start timed presentation” kullan; süre 30/55 saniyelik gerçek videoyu içerir. Videolarda altyazı, ek yazı veya ses yok; İngilizce konuşmacı notları eşliğinde sen anlatırsın. F11 tam ekran, boşluk duraklat/devam, oklar gezinme, Escape menü. <a href="SUNDAY_3_MINUTES.md">3 dakika</a> · <a href="SUNDAY_5_MINUTES.md">5 dakika</a> · <a href="JURY_Q_AND_A.md">Jüri soruları</a> · <a href="REHEARSAL_90_SECONDS.md">Kısa prova</a>.</p>
<p class="limit">Bu PowerPoint kurulumunda gömülü video oynatıcısı ilerlemediği için ana sunum çevrimdışı HTML'dir. Düzenlenebilir PowerPoint dosyaları, gerçek kayıttan zamanlanmış kareler kullanır; sürekli film HTML'de oynar. Resmî süreyi organizatörle netleştir ve pazar katkı alanını yalnızca gerçekleşmiş takım çalışmasıyla doldur.</p>
<h2>Bilimsel sınırlar ve kontroller</h2>
<p>Güncel yerel kelp yoğunluğu, ölçülmüş azalma, doğrulanmış habitat–dalga–varlık bağlantısı ve hasar fonksiyonları yok. Önlenmiş hasar ve geçerli ikame hizmet değeri hesaplanamadı; sıfır kabul edilmedi. 14/17 takson bölgesel bağlamdır. Eski restorasyon sınıflandırıcısı %63,45 yanlış pozitif oranıyla doğrulamayı geçmedi. Çıktı, saha araştırmasını yönlendiren bir ön değerlendirmedir.</p>
<p><a href="DELIVERY_STATUS.json">Gerçek test sonuçları</a> · <a href="CONSISTENCY_CHECK.json">Sürüm/senaryo tutarlılığı</a> · <a href="PRESENTATION_SCENARIO.json">Kesin girdiler ve hesap</a> · <a href="VISUAL_ASSETS_AND_SOURCES.md">Kaynaklar</a>. Eski paketler korunuyor; “SUPERSEDED_READ_FIRST.txt” dosyaları güncel yolu gösterir. Araştırma verileri değiştirilmedi.</p></html>'''
(O/'KULLANIM_TR.html').write_text(body,encoding='utf8')
(O/'SCENARIO_AND_REPRODUCTION.md').write_text(f'''# Single presentation scenario

Build `{e['build_id']}`. Scenario `{e['id']}`.

The presentation uses the default whole seven-cell pilot, 1.75 ha of nominal model geometry. These are not measured kelp boundaries. The short and long films temporarily vary water level and independent cost share, then restore the baseline before downloading the HTML report.

Exact inputs and calculated outputs: PRESENTATION_SCENARIO.json. Reproduce with START_DEMO.bat, choose the whole pilot and the inputs in that file. The active app identifies matching inputs as the presentation baseline. Run REBUILD_DEMO.bat then CHECK_DEMO.bat to rebuild and check the application. A rebuilt app with a different ID requires rerecording the media and regenerating all decks.

Conditional capital: {capital}; annualised capital: {annual}/year. Geometric candidate coastline: {r['comparison_length_m']:.8f} m. These are nominal funding-rate comparisons, not verified protected frontage, avoided damage or validated ecosystem-service value. No inflation conversion or local engineering design is implied. Three replacement-cost validity gates remain false.

Report export: Download HTML report produces self-contained HTML. Print / Save as PDF is the offline PDF route; use A4, 100% and no browser headers/footers. ASSESSMENT_PILOT.pdf is the actual downloaded HTML printed through Chrome, not a separately invented report.

Production sequence: record_visual_demo.mjs full / short; extract_release_frames.py; build_visual_pitch.mjs; finish_visual_pitch.ps1; normalize_visual_package.py; finalize_visual_pitch.mjs; verify_visual_powerpoint.ps1 -Final; prepare_visual_delivery.py; write_release_handover.py. Finalized PPTX files are immutable outputs: for another release use a fresh folder rather than overwriting them. Verify with browser_visual_delivery.mjs, delivery_file_checks.mjs, live_visual_rehearsal.ps1 and audit_jury_release.py.
''',encoding='utf8')
(R/'BASLA_BURADAN_TR.md').write_text(fr'''# Ocean Hackathon — güncel kullanım, 14 Ekim 2026

Uygulama sürümü **{e['build_id']}**. Sunum senaryosu **{e['id']}**.

- **Uygulama:** `C:\Users\Elif\Desktop\OCEANHACKATHON\START_DEMO.bat` dosyasına çift tıkla; yerel sunucu penceresini açık tut.
- **Jüri:** `C:\Users\Elif\Desktop\OCEANHACKATHON\START_JURY_PRESENTATION.bat` dosyasına çift tıkla. Güncel paket `C:\Users\Elif\Desktop\OCEANHACKATHON\outputs\jury_release_20261014` içindedir. Eski klasörlerle karıştırma.
- **Cuma/pazar:** Menüden Friday invitation ya da 3/5 dakikalık pazar sunumu seç. Videolar altyazısız, ek yazısız ve sessizdir; İngilizce konuşmacı notları eşliğinde sen anlatırsın. Film aynı sayfada oynar. F11 tam ekran, boşluk duraklat/devam, oklar gezinme, Escape menü.
- **Rapor:** Alan seç → kanıtları incele → modeli ve maliyet varsayımlarını çalıştır → Generate Assessment Report. Download HTML report bağımsız HTML indirir. Print / Save as PDF ile A4, %100 ve üst/alt bilgiler kapalı seçerek PDF kaydet. Doğrudan tek tık PDF indirme özelliği yoktur; gerçek indirmeden üretilmiş örnek ASSESSMENT_PILOT.pdf pakettedir.

Sunum başlangıç senaryosu varsayılan yedi hücre / 1,75 ha, yön farkı 0°, su seviyesi +0 m, katsayı interpolasyonu ×1, geometrik aday kıyı, bağımsız maliyet payı %100, birim fiyat çarpanı 1, %4 iskonto ve 50 yıldır. Aday kıyı {r['comparison_length_m']:.2f} m; koşullu dalga yüksekliği azalması %{r['height_fraction']*100:.2f}, enerji azalması %{r['energy_fraction']*100:.2f}. Sermaye karşılaştırması **{capital}**, yıllıklaştırılmış sermaye **{annual}/yıl**. Bunlar önlenmiş hasar, yıllık tasarruf veya doğrulanmış ekosistem değeri değildir. Videolar geçici değişikliklerden sonra raporu bu başlangıç değerleriyle indirir.

Güncel kelp yoğunluğu, ölçülmüş azalma ve kıyı varlıklarına ulaşan koruma doğrulanmadı. Hasar fonksiyonları ve ikame hizmetin geçerlilik koşulları eksik. Gerçek önlenmiş hasar bilinmiyor; sıfır değil. Bölgesel 14/17 takson yerel tür zenginliği değildir. Eski sınıflandırıcı %63,45 yanlış pozitif oranıyla doğrulamayı geçmedi; restorasyon çıktısı saha araştırması önceliğidir.

PowerPoint'in gömülü video oynatıcısı bu bilgisayarda ilerlemedi. Ana yol, tam süreli test edilmiş çevrimdışı HTML sunumudur. Düzenlenebilir PPTX dosyaları gerçek kayıttan zamanlanmış kareler kullanır.

Kontroller: 34 sayısal test, 13 tarayıcı temel kontrolü, 11 anlatım kontrolü ve 6 değerlendirme akışı kontrolü geçti. Gerçek HTML indirme, üç sayfalık PDF ve mobil/çevrimdışı kullanım test edildi. Sunumun 13 slaytı PowerPoint ile yeniden açılıp çizdirildi; 3/5 dakikalık çevrimdışı provalar, video çözme ve ortak sürüm/senaryo denetimi geçti. Kesin kayıtlar güncel paketin DELIVERY_STATUS.json ve CONSISTENCY_CHECK.json dosyalarındadır.

Detaylı kısa kullanım: güncel pakette KULLANIM_TR.html / KULLANIM_TR.pdf. Kaynaktan üretmek için REBUILD_DEMO.bat, test için CHECK_DEMO.bat. Yeni bir uygulama sürümü üretirsen sunum/video eşleşmesini yeniden kontrol et. Orijinal araştırma girdilerinin özet değerleri korunmuştur.
''',encoding='utf8')
print('Handover generated for',e['build_id'],e['id'])
