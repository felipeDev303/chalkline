# Demo video script (under 2 minutes)

Screen recording of the live demo at 1440 × 900 or larger, with a voice-over. No music
(the rules forbid third-party music; silence or our own voice only), no real league,
club or player marks: everything on screen is synthetic.

**Before recording:** open the live demo, confirm the badge reads **Foundry live**, pick
**Halvesham Town v Westerlake City**, leave it at kick-off. Keep the browser zoom at 100%
and hide bookmarks. Do one dry run so every narrative is already cached (instant).

| Time | On screen (clicks) | Voice-over |
|---|---|---|
| 0:00-0:11 | The broadcast view at kick-off, perspective pitch, **Foundry live** badge. | "AI can now explain a football match live. But a confident sentence with a wrong number is worse than silence. Chalkline proves every number it shows." |
| 0:11-0:30 | **Next story** → "The run that made it" (11'). The run replays without it, then with it; the control bars fill (52% → 92%). | "This pass worked because of a run nobody sees in the stats. Chalkline undoes Cyril Ulkov's run, recomputes the space, and shows the receiver's control rising from 52 to 92 percent. On planted runs, it credits the right runner 86 percent of the time." |
| 0:30-0:47 | The desk's verified explanation beside it. Click an underlined sentence: the evidence panel opens (facts, method, "cannot tell"). Tick **Side by side**, switch **ES**, then back to **EN**. | "An agent desk on Microsoft Agent Framework and Foundry explains it: an analyst picks the tools, a narrator writes, and a verifier agent checks every number against the facts each sentence cites. For a fan or an analyst, in English or Spanish." |
| 0:47-1:01 | **Next goal** (27'). The goal airs as a lower third; the win-probability bar jumps (45% → 77%). Do not press play yet: the fact-check example needs this moment (52%). | "When Westerlake score, Chalkline says why it matters: their chance of winning goes from 45 to 77 percent. A producer agent decides what goes on air, knowing only what has happened so far." |
| 1:01-1:14 | **Fact-check a line** → **Try an example**: "…85% possession" flagged in red; "the data says 52%". | "It checks humans too. A commentator says 85 percent possession; at this minute the data says 52. No model involved: deterministic, instant." |
| 1:14-1:40 | **How it's measured** dialog. Hold on the table. | "Every claim is measured. The simulator plants the truth, pressing spells, off-ball runs, the real probability of every shot, in a file the metrics and agents can never read. Our expected goals land within 0.014 of the truth. And without the verifier, a single agent airs wrong numbers 35 to 40 percent of the time. With it: zero." |
| 1:40-1:51 | Quick cut: `docs/DEPLOY.md` table or the Azure portal resource group (Container Apps, Foundry, Blob), then back to the app. | "It runs on Azure Container Apps with Microsoft Foundry, keyless end to end with managed identity, with verified narratives cached in Blob so every viewer gets them instantly." |
| 1:51-1:56 | Back to the demo tab; press play: players glide, the telestrator draws the move. | "Chalkline. Every number, proven." |

**Voice:** synthetic, Azure AI Speech `en-GB-RyanNeural`, generated from the table above
by `uv run python scripts/voiceover.py` (keyless, on the Foundry account). It writes one
WAV per scene to `data/voiceover/` (not committed). Measured: 112 s of speech; with a
short pause between scenes the cut runs about 1:56. Times above follow the audio. If
the voice-over text changes, run the script again; trim the Azure line first if the cut
runs long.

**Upload:** YouTube or Vimeo, public or unlisted with a public link, title "Chalkline:
verified match intelligence (Inside the Game hackathon)". Paste the link into
`docs/SUBMISSION.md` and the form.
