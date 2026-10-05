# README creative brief

Read this before generating any README asset. Every Higgsfield prompt starts with the style string below.

## Evidence

- **Name:** Hermes is the messenger: the plugin sits on the road between your message and your model. The existing mascot is a ghost, a ghostwriter that rewrites your words without taking your name off them.
- **Job in the user's world:** a mail clerk who takes your scribbled, crumpled note and copies it onto a crisp card before it goes out, with your original still attached ("your message wins if the two conflict").
- **Voice:** plain, careful, unfussy. Sources: "You type the way you always do." (old README), "Fails safe." (old README), "Every detail survives" (old README), "never rewritten by the main model instead" (`config.yaml.example`).
- **Existing brand** (these files were removed later, see [Removed files](#removed-files)): `assets/logo.webp` (cream ghost, wavy lavender hem, two oval lavender eyes, small smile, on sage), `assets/banner.webp` (crumpled scribbled note, ghost, tidy card), `assets/desk.webp` (the ghost as a matte figure on a sunny desk). Measured colors: sage `#8FA586`, cream `#FBF6EC`, lavender `#B48EE9`; old badge violet `#7B5CC4`; old title plum `#3F3354`.
- **Visual references:**
  - `refs/ref-1-logo.png` (from `assets/logo.webp`): keep the ghost's exact silhouette and face, no arms or feet, matte finish.
  - `refs/ref-2-banner.png` (from `assets/banner.webp`): keep the props (crumpled scribbled note, tidy card) and the sage ground.
  - `refs/ref-3-desk.png` (from `assets/desk.webp`): keep the soft window light and contact shadow only. Not passed to generators: its laptop and keyboard invite fake-UI props.

## Directions shown

| | A (chosen) | B | C |
|---|---|---|---|
| Medium | Stop-motion claymation diorama | Macro product photography | Two-colour risograph, 1960s Swiss postal poster |
| Metaphor | Clay ghost at a tiny post-office desk smoothing a crumpled letter into a crisp card | Vinyl ghost on a sunlit desk between a crumpled sticky note and a typed card | Mail chute: scribbled letter in the top slot, typed telegram out the bottom |
| Pitch | A clay ghostwriter smooths your scribbled note into a crisp card. | Golden-hour desk: a crumpled note goes in, a crisp card comes out. | Swiss postal poster: scribbled letter in, typed telegram out. |
| Preview | z-image/turbo `ead51f0f-8a55-40a2-9fc2-ea1979787866` | `45c062f7-d878-4b4e-92b1-ac177042545e` | `1ded6ddd-b7b1-40c0-9fe6-f0a5b07c4cbe` |

Picked A (agent's pick; the user wasn't asked mid-run): its metaphor carries the name (Hermes the messenger, a mail desk) and the job (rewriting the letter before it goes out), and its clay finish matches the existing ghost logo. The A preview gave the ghost arms and feet, so the metaphor now pins the logo's shape.

## Locked direction

- **Metaphor:** a small cream plasticine ghost (no arms, no feet, wavy lavender hem, two oval lavender eyes, small smile) at a tiny violet clay post-office writing desk, smoothing a crumpled scribbled letter into a crisp blank index card beside a little outbox tray.
- **Palette:** sage `#8FA586` (ground), cream `#FBF6EC`, lavender `#B48EE9`, violet `#7B5CC4`, plum `#3F3354` (dark ground and ink).
- **Style string** (36 words; every prompt starts with it):

  > Stop-motion claymation diorama, handmade miniature set with paper props, soft window light from the left, matte plasticine with fingerprints and tool marks, paper fibers, gentle contact shadows, palette sage #8FA586, cream #FBF6EC, lavender #B48EE9, violet #7B5CC4, plum #3F3354, calm uncluttered composition

- **Light banner clause:** `on a pale cream wall #FBF6EC` (replaces the dark plum wall).
- **Typeface:** display Instrument Serif 400 (the name, condensed: the 23-character name ends at x=816 of 1280, so the art keeps its right third); text Nunito 600 (tagline); clip terminal text JetBrains Mono 400. All from Google Fonts via Fontsource.
- **brag tone:** `default`, freeform "cozy stop-motion short about a tiny ghostwriter at the mail desk".
- **Motion (clip):** objects settle like paper landing on a desk, no bounce; one slow push-in per scene at most, never a whip; text slides in like a card pushed across the desk, then holds.
- **Tagline:** Messy message in, clear prompt out.

## Generation log

Contact sheets judged at 830 px; composed banners checked in Chromium (GitHub renders the SVG in the browser; `rsvg-convert` ignores the embedded `@font-face` and shows a fallback sans, so it is not a valid font check).

### Banner art, dark (`marketing-studio/image/flare`, 21:9, 2k, quality high)

References: `ref-1-logo.png`, `ref-2-banner.png`.

| Round | Candidate | Prompt change | Slop score + tells | Hard fails | Verdict |
|---|---|---|---|---|---|
| 1 | c1 `f25eabed` | (initial prompt) | 0 | Banner layout: subject too large; the name runs into the crumpled note, and the crop clips the ghost's head | rejected |
| 1 | c2 `a14f5ac5` | (initial prompt) | 0 | Banner layout: the name's last letters overlap the ghost's hem | rejected |
| 1 | c3 `c13ab75e` | (initial prompt) | 0 | Banner layout: the name overlaps the ghost; head at the crop edge | rejected |
| 2 | c1 `62563663` | composition clause: "wide shot with a small subject in the far right quarter: the ghost and the desk span only from 72% to 95% of the width, plain wall above the head and floor below the desk, the left 70% is an empty plain plum clay wall" | 0 | none | passed; ghost smallest at 830 px |
| 2 | c2 `0f82a393` | same | 0 | none | **accepted** (largest, most legible ghost; the scalloped desk apron echoes the hem) |
| 2 | c3 `270c0404` | same | 0 | none | passed |

Routing: every round-1 failure was composition (Banner layout), so round 2 changed only the framing clause. `measure.py` on the accepted art: 98% on-palette, no OCR words.

### Banner art, light (`marketing-studio/image/flare`, 21:9, 2k, quality high)

References: accepted dark art as reference image 1, then `ref-1-logo.png`, `ref-2-banner.png`. Prompt: the style string, `on a pale cream wall #FBF6EC`, the metaphor, "match the style, palette and lighting of reference image 1", the round-2 framing, "the left 60% of the frame is plain empty cream #FBF6EC wall with no objects".

| Round | Candidate | Prompt change | Slop score + tells | Hard fails | Verdict |
|---|---|---|---|---|---|
| 1 | c1 `11faa507` | (initial prompt) | 0 | none | passed; crumpled note crowds the name's end |
| 1 | c2 `d90b917b` | (initial prompt) | 0 | none | **accepted** (clearest gap between name and subject) |
| 1 | c3 `af80a12e` | (initial prompt) | 0 | none | passed |

### Composed banners (`banner.py`, Instrument Serif 400 + Nunito 600, no `--logo`)

- `--logo` is left off: the ghost is already the art's subject, and the logo would push the name (739 px at 80 px size) into it.
- Tagline contrast, measured on the 830 px render: dark 11.3:1, light 8.8:1 (floor 4.5:1).
- Social preview skipped: at 1280x640 `banner.py` sets the name at 128 px (about 1180 px wide), which covers the art.

### Clip art, 16:9 (`marketing-studio/image/flare`, 16:9, 2k, quality high)

For the clip's reveal and outro: the 21:9 banner art cover-cropped to 16:9 pushed the desk to x=50%, leaving no room for the name and the install line.
References: accepted dark art as reference image 1, then `ref-1-logo.png`, `ref-2-banner.png`. Prompt: the style string, the metaphor, a sage `#8FA586` clay floor, "match the style, palette and lighting of reference image 1", "16:9 wide shot ... the ghost and the desk span only from 70% to 94% of the width ... the left 66% is an empty plain plum clay wall above an empty sage floor".

| Round | Candidate | Prompt change | Slop score + tells | Hard fails | Verdict |
|---|---|---|---|---|---|
| 1 | c1 `90e08567` | (initial prompt) | 0 | none | **accepted** (best vertical balance; wall for the name, floor for the install line) |
| 1 | c2 `9877c3b4` | (initial prompt) | 0 | none | passed |
| 1 | c3 `1ab68dde` | (initial prompt) | 0 | none | passed |

Measured on the accepted art: wall `#3F3246`, floor `#8B9A7A`. The clip's CSS scenes use these, so the crossfades between art and CSS scenes don't shift color.

### Clip (full brag, Hyperframes 0.8.105)

- Brief, plan and composition: `brag-output/` (gitignored). Tone `default`, "cozy stop-motion short about a tiny ghostwriter at the mail desk". Fonts as above, plus JetBrains Mono for terminal text.
- `hyperframes check`: 0 lint, 0 runtime, 0 layout issues across 9 samples, 22/22 WCAG AA contrast checks.
- Key frames reviewed at 830 px before rendering; a draft render was reviewed at one frame per second.
- Fixes during review: titles delayed until the outgoing scene has faded (no title overlap); the paperclip redrawn; the S3 ghost enlarged; scene 5 compacted so its GIF crop stays legible; the outro name moved onto the 21.59 s beat after the handoff.
- Audio: music bed vol-9. The volume lane's values are absolute and override `data-volume`, so the 0.33 level lives in the lane. Music alone peaks at -13.3 dB, and the whole mix measures -23.9 LUFS integrated.
- Final: 24.2 s, 1920x1080, H.264 + AAC, 7.8 MB (under GitHub's 10 MB free-plan limit). The poster at 10.2 s is baked in as frame 0.

### Feature GIFs (cut from the clip, 12 fps, 800 px, 128 colours)

| File | Beat | Window (S-E, hold T) | Crop (w:h:x:y) | Size | First vs last frame |
|---|---|---|---|---|---|
| `feature-1.gif` | the optimized prompt prints | 7.2-10.75, T 10.2 | 1156:650:644:236 | 668 KB | 0.01/255 |
| `feature-2.gif` | message stays; rewrite attached; failure sends as typed | 11.25-15.85, T 15.2 | 1240:698:110:236 | 1.5 MB | 0.03/255 |
| `feature-3.gif` | `/optimizer 2 3`, candidates, judge | 16.35-20.9, T 20.4 | 1320:742:110:236 | 1.1 MB | 0.02/255 |

The crops keep text at about 11 px or larger at the README's 450 px column width. The first feature-1 cut caught a sliver of the rotated note at its left edge, so the crop was moved right.

### Clip hosting

The README embeds the clip from GitHub as `https://github.com/user-attachments/assets/14944e57-ec38-4a20-9dad-3906395ed74e` (the inline-player form; the first upload, `03b4b68f-…`, now returns 404). The in-repo `demo.mp4` and `demo-poster.jpg` were removed once it was uploaded, because Hermes installs plugins by cloning the repo. Both remain in git history at commit `6212276`, outside main. PR #7's branch is deleted, so fetch it with `git fetch origin pull/7/head`.

## Removed files

Only the old README used `assets/`, so it was removed after the redesign: `logo.webp` (8 KB), `banner.webp` (27 KB), `desk.webp` (37 KB) and `social-preview.png` (323 KB, 1280x640, never set as the repo's social preview). They stay in git history. Restore one from the commit before the removal: `git checkout bee80e3 -- assets/logo.webp`.

## Template 6 (launch page + bento), 2026-10-05

The README moved to the readme-enhancer skill's proposal 6 layout: hero, CTA buttons, nav, clip, eight spec cards, a bento grid of
animated WebP tiles, How it works, Quick start, Commands, Configuration, Contributing (contribute card), License, outro. The clip,
the banner art and the BRIEF above are unchanged. Preflight this run: no higgsfield-api, no brag, no system Chromium (Playwright's
`/opt/pw-browsers/chromium` was used for every screenshot and render), no `gh` GraphQL (repo visibility read over REST: public).
The skill's `button.py`, `strip.py` and `tile.py` do not exist yet, so the assets were generated by three throwaway scripts kept
outside the repo (`gen_static.py`, `tiles.py` + `frames.mjs` + `encode.py`); their recipes are recorded here so a later run can
rebuild them.

### Fonts

Instrument Serif 400 (display), Nunito 400/600/700 (text) and JetBrains Mono 400/600 (terminal text), the full TTFs from Google
Fonts (the Fontsource CDN is blocked from this environment; the latin subsets lack the box-drawing, `→` and `│` glyphs the real
output uses). Static SVGs embed per-file subsets made with `pyftsubset` (each card carries 10-30 KB of font data); the tiles load
the full fonts while rendering, so nothing is embedded in the WebP. `✦` and `✓` fall back to DejaVu Sans in the tiles.

### Static SVGs (buttons, rule, spec cards, contribute card, outro, banner animation)

- Palette per theme. Light: white cards, stroke `#E4DED3`, ink plum `#3F3354`, muted `#6E6680`, accent violet `#7B5CC4`, terminal
  ground cream `#FBF6EC`. Dark: cards `#1A1523` on GitHub's `#0D1117`, stroke `#352C47`, ink cream `#FBF6EC`, accent lavender
  `#B48EE9`, terminal ground `#2A2338`, bar plum `#3F3354`. Sage `#8FA586` is the second accent (list dots, the contribute mark).
- Buttons 48 px tall (shown at 44): "Get started" filled violet with cream text (4.6:1), "Watch the demo" outlined. No docs button:
  there is no docs site.
- Spec cards 432x270 with a 16/10 px transparent half-gutter, card 400x250, rx 22. Values in Instrument Serif, auto-shrunk to the
  328 px column with fontTools metrics; the install card in JetBrains Mono on three lines. Eight facts, each verified: install
  (ran this session, see below), Hermes v0.20.1+, CLI/TUI/desktop, any Hermes provider or OpenAI-style URL (`engine.resolve_endpoint`),
  4 context messages (`config.yaml.example`), one context block (`hook.INJECTION`), 0 extra packages (`AGENTS.md`), MIT.
- Contribute card 1600x300: the ghost mark (the BRIEF's mascot drawn as an SVG path) on a sage disc inside a dashed lavender ring.
  Used because the contributors API lists one person plus renovate[bot].
- Outro 1600x260: the install command in JetBrains Mono, one line of text, a small accent ring.
- Banner: the 2026-10-02 art and text kept; two SMIL animations added by hand, per the BRIEF's motion line. The art is 48 px wider
  than the frame and drifts `0 → -48 → 0` over 30 s (one slow move, no bounce); the tagline slides in 36 px from the left with an
  ease-out spline after a 0.4 s beat and then holds (`fill="freeze"`). The name does not move.

| Asset | Round | Change | Verdict |
|---|---|---|---|
| all static SVGs, light + dark | 1 | (initial) | accepted: contact sheet at 830 px viewed in Chromium, fonts embedded, nothing clipped |

### Bento tiles (animated WebP, 10 fps, libwebp quality 82, alpha kept)

Each tile is an HTML page whose `window.render(t)` sets the whole state for time t (typed text by character count, printed lines
by start time, a terminal view that scrolls like a terminal, scene crossfades), stepped by Playwright at 10 fps and screenshotted
with a transparent background, then encoded with Pillow. Frames are deterministic, so a rebuild gives the same file. Geometry as
the proposal's sample: 424x414 for a 400x400 card (12/7 px half-gutter), 848x414, 424x838 (two cards, 24 px apart), 848x838, rx 24.

Every terminal line is real: `/optimizer` replies and the `describe()` block captured from the plugin running under Hermes v0.21.5
(`capture.py`), the fallback error from a real hook run against a refused port, the install output from
`hermes plugins install cosminfuica/hermes-prompt-optimizer --enable` into a fresh `HERMES_HOME`, and lines from
`config.yaml.example`. The demo message and its rewrite are the clip's (scene 2 and 3 of the 2026-10-02 brag), with the
rewrite's em dashes written as hyphens. The settings-file path in the menu is `/home/you/.hermes/...`.

| Tile | Content | Length | Size light / dark |
|---|---|---|---|
| `tile-preview` | three screens: the rewrite in a chat, `/optimizer`, `/optimizer 2 3` then a best-of-3 rewrite; chip + line per screen, dot indicator | 19.5 s | 1.5 / 1.5 MB |
| `tile-stack-1-2` | feature 1 (typed message, `✦ optimized prompt` block) over feature 2 (the message as typed, then the `<optimized_prompt>` block that rides beside it) | 6.8 s | 342 / 345 KB |
| `tile-feature-3` | `/optimized` after the optimizer is down: the real "stopped Hermes from using main-model instead" reply | 5.6 s | 44 / 45 KB |
| `tile-feature-4` | the `per_model` keys of `config.yaml.example` | 5.6 s | 107 / 111 KB |
| `tile-feature-5` | the desktop composer banner (`desktop/plugin.js` strings: "Optimizing prompt…", "Optimized · model · 1.8s"), then expanded | 7.0 s | 48 / 49 KB |
| `tile-code` | the install command typed, its full output scrolling | 7.6 s | 410 / 420 KB |
| `tile-list` | providers the rewrite runs on, verified in Hermes' `PROVIDER_REGISTRY` (nous, anthropic, openrouter, lmstudio) and the Ollama default `base_url` | 5.4 s | 44 / 46 KB |

| Round | Change | Verdict |
|---|---|---|
| 1 | (initial) | rejected: feature 4 title overflowed the card, the pane tile clipped the message's fourth line, the preview faded out at the loop seam and ran 21.9 s |
| 2 | title "Shaped for Claude, GPT, Gemini" plus fontTools auto-fit; pane heights 102/86; last scene holds; faster typing and 50 ms menu lines (19.5 s) | accepted: light and dark sheets (five frames per tile at 33% / 66% of 830 px) and full-size end frames viewed |

Slop diagnosis does not apply (no generated imagery); the consistency check is the shared palette, typefaces and card geometry
across the banner, cards and tiles. The three feature GIFs cut from the clip (`feature-1..3.gif`) were removed with the feature
table; they stay in git history at the commit before this change.
