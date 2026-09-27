# Theming & Layout plan (v0.4)

## Layout change (agreed)
Keyboard IS the game: the A-Z canvas takes ~70% of the viewport, dead-centre.
Leaderboard drops BELOW the race (not a side column), auto-hides while racing,
or collapses to a slim "view board" tab when someone wants to peek between runs.
Mobile: board renders below the fold, tap-to-expand.

Implementation: two wrapper rows (.wrap becomes .raceRow + .boardRow).
Race panel = flex 2 2, board panel = flex 1 1 min 260px, stacked under race at
max-height 40vh with its own scroll; during running state board gets
collapsed-height + dimmed (already half-built — opacity/pointerEvents).

## Theme system (v0.4)
Move all colours/fonts into CSS custom properties under <body data-theme="...">,
store choice in localStorage key as_theme. Selector chips in footer.

### Candidate themes
1. "Arcade Noir" (current default) — deep navy-black, neon cyan/magenta/gold.
   Highest kid-appeal; matches brand.
2. "Paper Sprint" — off-white paper, ink-black type, teal accents, serif
   headline. Calm daylight schoolroom feel; better for print-style screenshots
   and dyslexia-friendly readers.
3. "Terminal '86" — phosphor green-on-black, monospace, CRT scanlines
   dialled to 22%. Speedrun-hacker aesthetic. Slice is subtle: terminals
   signal "serious typing" for older kids/adults.
4. "Sunset Arcade" — warm peach-rose-violet gradient background, pastel
   keyplates, cream text. Quieter palette for ADHD-sensitive players.
5. "Ocean Deep" — midnight blue, aqua/coral accents, bubble-like letters.
   Calming night option; pairs with audio blips pitched like water drops.
6. "Retro Mario" — sky blue, brick red, gold stars; letter tiles look like
   blocks/floating '?' boxes. Crowd-pleaser for the boys' age band (licensed
   LOOK-ALIKE note: original assets off-limits, vibe only).

### Recommendation
Ship Arcade Noir (default) + Paper Sprint + Terminal '86 first — one light,
one neon, one retro. Then add Sunset Arcade and Ocean Deep for evening play,
and Retro Mario look-alike LAST (needs a license-safe asset pass).
Theme picker chips live in the footer; preference persists across sessions.

### ADHD-fit note
Arcade Noir default stays; OFFER "Calm mode" toggle = Sunset Arcade palette +
slower pulse animation + reduced particle count, so play intensity is
kid-adjustable without losing the game's identity.
