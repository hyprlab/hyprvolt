# Design system

The interface comes from Hyprfeed's "electric editorial" design: Inter
everywhere, warm neutrals, and one accent color spent sparingly. Everything is
in `static/css/app.css`, hand-written, in the order this page follows.

## Principles

- **The accent is scarce.** It marks the brand, new items, and the active
  state (the current nav row, chip, focused field). Used anywhere else it
  stops meaning anything.
- **Surfaces carry the hierarchy**, not borders and shadows: `--bg` for the
  page, `--panel` for the sidebar and quiet containers, `--surface` for cards
  and dialogs, `--field` for inputs.
- **Motion explains where something went.** The sheet rises in from below and
  leaves through the top, toward the toast that confirms what happened. Every
  animation is off under `prefers-reduced-motion`.
- **Nothing shifts.** List rows keep their grid cells when a marker hides; the
  settings window keeps its size between sections; the scrollbar gutter is
  reserved so opening a dialog doesn't move the page.
- **Self-contained.** Inter is embedded, icons are inline SVG, and nothing is
  loaded from a CDN. Turnstile, when enabled, is the only third-party request.

## Tokens

Set on `:root` and per theme on `html[data-theme="light"|"dark"]`.

| Token | Use |
| --- | --- |
| `--accent`, `--accent-ink`, `--accent-glow` | The brand color, text on it, and its glow. The only brand values in the file. |
| `--bg`, `--panel`, `--surface`, `--field` | The four surface levels |
| `--ink`, `--muted`, `--faint` | Text: primary, secondary, tertiary |
| `--line`, `--line-strong` | Rules and borders |
| `--wash` | The accent at low opacity: hover and active backgrounds |
| `--scrim` | Behind dialogs and the mobile sidebar |
| `--danger` | Destructive actions and errors |
| `--radius`, `--radius-sm` | 14px for cards and panels, 10px for controls |
| `--shadow-1`, `--shadow-2` | Resting and raised |
| `--sidebar-w`, `--topbar-h` | Shell dimensions |

To rebrand, change the three accent tokens in both themes (the dark theme uses
a slightly different accent for contrast) and redraw the mark.

## Type

Inter Variable, 15px body at 1.55. Headings use heavy weights (750 to 850)
with negative tracking (-0.02em to -0.035em). Labels are 11px, 650 to 700
weight, uppercase, tracked +0.07em to +0.09em, in `--muted` or `--faint`.
Long-form text uses `.prose` at 16.5px and 1.72.

## Components

| Class | What it is |
| --- | --- |
| `.btn` + `--primary`, `--ghost`, `--danger`, `--block`, `--xs` | Buttons. One primary per view. |
| `.iconbtn` + `--sm`, `--danger`, `.is-busy` | Square icon buttons; `.is-busy` spins the icon |
| `.field`, `.field-label`, `.check`, `.hint`, `.form-error` | Form parts |
| `.seg` | Segmented control over radio inputs |
| `.theme-picker`, `.theme-chip` | Chip-style radio group |
| `.chip`, `.chip--muted`, `.count`, `.count--accent`, `.title-chip` | Small labels and counters |
| `.shell`, `.sidebar`, `.sidebar-head/-scroll/-foot` | The layout. The head and foot stay pinned; only the middle scrolls. |
| `.navitem`, `.sidebar-label`, `.sidelist`, `.sideitem` | Sidebar rows. `.is-active` adds the wash and an inset accent bar. |
| `.topbar`, `.context-title`, `.topbar-actions` | The sticky, blurred bar over the content |
| `.searchpill`, `.viewswitch`, `.menu`/`.menubtn`/`.menupop`/`.menuopt` | Topbar controls |
| `.card`, `.row`, `.kicker`, `.new-dot`, `.pinbtn`, `.is-done` | Records as cards or list rows |
| `.empty`, `.pager`, `.pager-end` | Empty states and paging |
| `.modal`, `.modal--wide`, `.modal-head`, `.modal-body` | Dialogs, built on `<dialog>` |
| `.settings`, `.settings-nav`, `.settings-navitem`, `.settings-head`, `.settings-pane` | The settings window: a rail of sections beside the chosen one; on phones a list that slides into each section |
| `.sheet`, `.sheet-bar`, `.sheet-article`, `.prose` | The full-height detail view |
| `.palette` and its parts | The Ctrl/Cmd+K search |
| `.toast`, `.toast--error`, `.toast-action` | Confirmations under the topbar, with an optional action such as Undo |
| `.about-hero`, `.tech-stack`, `.release-list` | The About section |
| `.auth-card`, `.auth-mark`, `.flash`, `.wizard`, `.wiz-*`, `.error-code` | Sign-in, setup and error pages |
| `.ptr` | Pull to refresh on touch devices |

## Interface rules

- **Errors are shown; success mostly isn't.** A failed action always says what
  went wrong, in a sentence, as an inline form error or an error toast. A
  success toast is for actions whose result is not already visible (a saved
  preference, a deleted record with Undo), not for every click.
- **Undo instead of "Are you sure?"** for anything recoverable. A confirmation
  dialog is kept for what can't be undone: deleting an account.
- **Optimistic, then honest.** A toggle updates at once and rolls back with an
  error toast if the server refuses.
- **Every screen has a URL.** Filters, sort, view and the open record are query
  parameters.
- **A reload keeps your place.** Refreshing brings back the dialog that was
  open, as it was: the settings section and its scroll, a half-typed record,
  the search query. Every `<dialog>` gets this by default (one with nothing to
  remember simply reopens); `data-restore="off"` opts one out, and a dialog
  with state adds a save/restore pair to `dialogMemory` in `app.js`. Only a
  reload restores; arriving at the page any other way starts clean.
- **Keyboard first.** Every action in the sheet has a key, the palette opens
  from anywhere, and focus is always visible (`:focus-visible` draws the
  accent outline).
- **Phones get the same app.** Under 900px the sidebar becomes a drawer; under
  700px settings goes full screen as a list of sections, each opening with a
  Back button (Escape goes back too); under 560px the view switch moves into
  settings.
- **American spelling** in everything the interface says.
