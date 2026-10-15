# The Invisible Shield — English jury narration

Build: `6a84de90fe69`. Duration: 10:00 including the 75-second application video. The PowerPoint contains no speaker notes. Stage directions in brackets are not spoken. Slide 10 holds for 110 seconds: 35 seconds of speech followed by the 75-second video. The supplied timing is a rehearsable schedule, not a claim that a human speaker has completed a rehearsal.

## 00:00–00:35 — Slide 1: The Invisible Shield

What if the infrastructure protecting our coast is already alive?

Kelp is large brown seaweed. Underwater, it creates structure where marine life can shelter, feed and grow. It also interacts with moving water. That makes it worth examining when we think about coastal infrastructure.

Our project is The Invisible Shield. We connect evidence about this living habitat to decisions people make on land, while keeping the strength of that evidence visible.

[Let the three connections appear. At 00:35, move to slide 2. The opening underwater photograph is ecological context from Molène, France; the coast photograph is Sherkin, Ireland. Neither is a Cape Clear field observation.]

## 00:35–01:15 — Slide 2: What do we lose if we cannot see it?

Much of this habitat sits below the surface. A coastal planner may have an old survey, a few species records and several separate maps. Those pieces can be useful, but they rarely answer a planning question on their own.

This makes change harder to detect and research harder to prioritise. It can leave a possible ecological contribution outside the discussion altogether. We are describing a decision problem, rather than claiming that we measured habitat loss here.

If we cannot map it, we cannot account for it.

[Pause on the closing sentence. Transition at 01:15.]

## 01:15–02:00 — Slide 3: From fragmented maps to an integrated assessment

Kelp has been mapped before. The difficulty is connecting records collected at different times, for different purposes, with different levels of detail.

Our assessment brings those records into one place without pretending they are equivalent. A historical polygon stays historical. A dated observation retains its date and quality flags. Satellite evidence has its own interpretation. Waves, depth and coastal assets become inspectable alongside them.

The user can then test a physical hypothesis, explore independent funding assumptions and export an assessment that retains the evidence and the next research steps. This makes the gaps actionable.

[Follow the records into the map. Transition at 02:00.]

## 02:00–03:00 — Slide 4: How the system works

The workflow starts with public marine and geographic data. Python prepares the coordinates, spatial joins and quality flags. A deterministic engine calculates every physical and euro scenario.

The map keeps observations, historical references, assumptions and model outputs visually distinct. Machine learning was investigated for mapping, but we do not present an unvalidated classifier as current kelp truth.

Ask the Assessment adds a local Hybrid GraphRAG layer. It reads the selected inputs, follows relationships in a knowledge graph and retrieves relevant source text. An optional small local model helps route questions. The final answer comes from controlled evidence and the calculation engine, with citations and a clear boundary on what it proves.

The whole assessment also works offline, without the model running.

[Follow the five pipeline steps. Transition at 03:00.]

## 03:00–03:50 — Slide 5: Cape Clear: from ocean evidence to coastal context

Our main demonstration is Cape Clear, around South Harbour in Cork.

Here we can examine historical habitat references, dated kelp observations, offshore directional waves, bathymetry and mapped infrastructure in the same geographic context. A published seawall-repair tender also establishes a real engineering need at South Harbour.

The reference sources disagree at our selected point, and some records have coordinate or locality concerns. We show those issues directly. The current habitat footprint still needs verification.

Cape Clear therefore gives us a working conditional assessment. The roads and buildings on this map are candidates for investigation, with no claim that kelp protects them.

[Let the map reach South Harbour. Transition at 03:50.]

## 03:50–04:40 — Slide 6: What changes with and without habitat?

Watch the two scenarios enter the same assumed habitat cell with identical incoming waves.

Under the default depth, direction and laboratory coefficient assumptions, the model gives approximately 8.43 percent lower wave height across that cell. Removing habitat returns the relative height to one. Changing depth or direction changes the conditional result.

The calculation ends at the cell boundary. As we continue towards the coast, the evidence gap becomes visible. We have not calculated nearshore wave transformation, flooding or damage to a receptor. The depth datum and present habitat also need verification.

This is a testable physical hypothesis, with a clearly defined next modelling step.

[Leave the shoreline gap visible. Transition at 04:40.]

## 04:40–05:35 — Slide 7: From physical scenario to a transparent euro comparison

The economic comparison uses a separate calculation. The attenuation percentage does not determine the budget share.

For this example, we assume one hundred metres of comparison frontage. We multiply that length by published Irish engineering funding benchmarks and an independent one hundred percent budget share.

The pooled result is about 562 thousand euros. The low and high source rates show how much the comparator changes with the benchmark. At four percent over fifty years, the pooled annual equivalent is about 26 thousand euros per year.

These are funding comparisons. They are not verified savings, avoided damage or a valuation of kelp. The highlighted coastline illustrates the assumed length, not protected frontage or a surveyed tender alignment.

[Allow both chart groups to finish. Transition at 05:35.]

## 05:35–06:15 — Slide 8: Kelp is a living habitat

The ecological question matters alongside the physical one. Kelp structure can provide habitat used by different organisms and life stages. These connections explain why biodiversity belongs in a coastal assessment.

Inside our selected geographic rectangle, the inventory contains 154 records and 109 distinct taxon names. It mixes marine, shore and terrestrial records from different dates and providers.

Users can filter that inventory and inspect the underlying records. It does not establish the richness of a kelp bed or quantify a local fisheries benefit. Those questions require habitat-linked sampling.

[Let the ecological connections settle. Transition at 06:15.]

## 06:15–06:55 — Slide 9: Why monitoring and restoration matter

Monitoring helps us distinguish a plausible pressure from a measured change. Warming, storms, water quality and disturbance can all be relevant questions, but this application does not claim they were measured at a current Cape Clear bed.

Instead, it shows which evidence is available and what is missing. The next actions include verifying the habitat, resolving source disagreement and checking the physical connection to shore.

Restoration comes after that assessment. We first need to understand condition, pressures, substrate and feasibility. The product helps assign those investigations to the right expertise.

[Transition at 06:55.]

## 06:55–07:30 — Slide 10: What the user actually gets

A planner, local authority or research team can start with a supported area and move through one guided assessment.

They inspect evidence on a map, compare scenarios and ask what a result means. The report preserves their selected inputs and filters, so a colleague can see how the conclusion was reached.

The output supports a decision about the next investigation. It does not issue planning approval.

Here is the working application.

[At 07:30 play DEMO_75_SECONDS.mp4. Speak the separate VIDEO_LIVE_NARRATION.md over the silent video. Resume on slide 11 at 08:45.]

## 08:45–09:30 — Slide 11: What makes this innovative?

The contribution is the connection between ecology, coastal engineering and economics, with the evidence boundary carried through every step.

We have a working demonstrator using digital marine data. Its ambition is an end-to-end assessment that makes the missing links explicit. Its environmental and societal purpose is to guide better investigation before a coastal claim becomes an investment claim.

The local assistant explains calculations without generating new scientific values. Portable case, state and report contracts support transfer to another location after appropriate calibration.

The editable contribution fields are reserved for the team's actual work. They do not imply weekend contributions that have not yet happened.

[Point to the proof items without reading them as a checklist. Transition at 09:30.]

## 09:30–10:00 — Slide 12: Protect What We Cannot See

Coastal decisions become stronger when the evidence below the water is visible alongside the infrastructure above it.

The Invisible Shield helps people see that evidence, understand its implications and decide what to investigate next. It gives a potential natural contribution a place in the conversation, with the means to test it.

Protecting our coast should also mean understanding the nature that helps protect it.

[Hold the final image. Finish at 10:00.]
