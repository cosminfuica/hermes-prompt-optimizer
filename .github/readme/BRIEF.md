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
