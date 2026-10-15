# Video playback and optional manual PowerPoint insertion

Build `6a84de90fe69`. The final PPTX deliberately contains a poster on slide 10 and **no embedded movie**. Both supplied MP4s are independently decoded and played in Chrome. The PowerPoint automation compatibility checks were inconclusive because the test harness encountered slide/player indexing errors. They do not establish that PowerPoint cannot decode the movie. A further embedding attempt was stopped by automatic approval review as an out-of-scope repeat. The working final deck was preserved.

## Tested separate-player route

On this computer, `C:\Users\Elif\Desktop\OCEANHACKATHON\START_JURY_SHOW.bat` runs the native timed PowerPoint and opens the separate 75-second movie in Chrome at the slide-10 cue. It uses the already installed PowerPoint, Chrome and project Node/Playwright runtime. No model, network, audio or video embedding is needed. The final acceptance file records whether the full timed run passed. Allow the show to complete without interacting with its windows during the acceptance-style playback.

For a manual talk, open the PPTX and `DEMO_75_SECONDS.mp4` before starting. At 07:30, after 35 seconds on slide 10, switch to the movie and play from its start. At 08:45 return to slide 11. Slide 10's 110-second timing already reserves both narration and film. The 30-second film is a standalone backup; it shortens the talk by 45 seconds unless that time is used deliberately.

## Optional insertion in a copy of the deck

1. Save a copy of `INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pptx`. Keep the delivered original as fallback.
2. On slide 10, choose **Insert → Video → This Device**, then select `DEMO_75_SECONDS.mp4` from this folder. Embed the file rather than linking to a temporary path.
3. Size the movie to the full 16:9 slide. Retain the existing poster behind it. Do not add a thirteenth slide.
4. In the Animation Pane, give the movie an entrance effect and a Play effect that both begin **35 seconds after slide entry**. Use **With Previous** in the same slide-entry group, with a 35-second delay. Ensure it does not cover the narrative before that cue. Check the actual timeline rather than relying only on the Playback tab's “Automatically” setting.
5. Keep the movie at its full 75 seconds, with no trimming, audio, captions or looping. Keep slide 10's advance time at **01:50**. The complete schedule remains 600 seconds.
6. Save, close and reopen the copy in Microsoft PowerPoint. Play slide 10, verify that its narrative remains visible for 35 seconds, then verify the entire video and the transition to slide 11. If it does not work reliably on the presentation machine, use the separate-player route above.

## Recording boundary

The movies are real final-application captures at 1920×1080, encoded at 30 fps. Controls, focus rings, filter changes, calculations and report downloads are real. There are no added overlays or subtitles. Chrome's direct capture does not include the operating-system mouse pointer. The Windows capture helper timed out waiting for application permission, so no artificial cursor was added. This is a remaining recording limitation, not a claim that cursor capture passed.
