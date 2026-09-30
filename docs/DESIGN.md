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
| `--ink`, `--muted`, `--faint` | Text: primary, secondary, tertiary. Each reads at 4.5:1 or better (WCAG AA) on every surface in both themes; a new shade must too |
| `--line`, `--line-strong` | Rules and borders |
| `--wash` | The accent at low opacity: hover and active backgrounds |
| `--selected`, `--hover` | The chosen row in the sidebar, settings and search, and a row under the pointer: a grey a step darker than the panel in the light theme (the accent bar alone marks the choice), the wash in the dark |
| `--scrim` | Behind dialogs and the mobile sidebar |
| `--danger` | Destructive actions and errors; lighter in the dark theme, so it reads at 4.5:1 there as well, alert counts included |
| `--radius`, `--radius-sm` | 14px for cards and panels, 10px for controls |
| `--shadow-1`, `--shadow-2` | Resting and raised |
| `--sidebar-w`, `--topbar-h` | Shell dimensions |

To rebrand, change the three accent tokens in both themes (the dark theme uses
a slightly different accent for contrast) and replace the app icon:
`static/img/logo.svg` is the mark on every page and the favicon, and
`favicon-32.png` and `apple-touch-icon.png` are rendered from it (the touch
icon on a dark square, since iOS fills transparency with black).

## Type

Inter Variable, 15px body at 1.55. Headings use heavy weights (750 to 850)
with negative tracking (-0.02em to -0.035em). Labels are 11px, 650 to 700
weight, uppercase, tracked +0.07em to +0.09em, in `--muted` or `--faint`.
Long-form text uses `.prose` at 16.5px and 1.72.

## Components

| Class | What it is |
| --- | --- |
| `.btn` + `--primary`, `--ghost`, `--danger`, `--block`, `--xs` | Buttons. One primary per view. |
| `.iconbtn` + `--sm`, `--danger`, `.is-busy`, `[aria-pressed="true"]` | Square icon buttons; `.is-busy` spins the icon; pressed is a switch that is on (a user's access to secrets) |
| `.field`, `.field-label`, `.check`, `.hint`, `.form-error` | Form parts |
| `.field--narrow`, `.inline-form`, `.inst-grid`, `.stack` | A short input; a field and its button on one line; the Admin settings' grid of number fields; a form whose parts stack with even gaps |
| `.setting-label`, `.setting-label--spaced` | The small capitals heading a group in a tab, pane or card; `--spaced` puts room above one that follows content |
| `.manage-list`, `.manage-item`, `.manage-meta`, `.manage-title`, `.manage-sub` | Rows of things with their actions: users, backups, tokens, and most module tabs (ports, installations, secrets, DNS records). The title is one line, the sub line is quieter and cut with an ellipsis |
| `.link`, `.mono`, `.avatar` | A link in running text, underlined in the accent on hover; monospaced text (keys, compose files); a user's initial in a circle |
| `.seg`, `.seg--xs` | Segmented control over radio inputs; `--xs` inside a list row (a user's role) |
| `.guide-body`, `.guide-top`, `.guide`, `.guide-rail`, `.guide-step`, `.guide-row`, `.guide-nav` | The site setup guide, on a page of its own (`guide.html`: the brand and Exit setup, no shell): its steps down the side (the one being done marked as the settings rail marks its section), a step's rows as panels of fields, and Back and Skip on the left, the step's saves on the right |
| `.switch`, `.switch-track` | An on/off switch over a checkbox, for something that takes effect at once (a module) |
| `.theme-picker`, `.theme-chip` | Chip-style radio group |
| `.chip`, `.chip--muted`, `.count`, `.count--alert`, `.title-chip` | Small labels and counters. `--alert` is a count that needs attention (conflicts); a `.title-chip` link clears a filter |
| `.tagchip`, `.tagdot` | A tag, the same in every module; a link where it filters. The dot marks tags in the sidebar |
| `.shell`, `.sidebar`, `.sidebar-head/-scroll/-foot` | The layout. The head and foot stay pinned; only the middle scrolls. |
| `.navitem`, `.sidebar-label`, `.sidelist`, `.sidelist--nested`, `.sideitem` | Sidebar rows: a module is a `.navitem`; the open module's types and filters are a nested list under it. `.is-active` adds the wash and an inset accent bar. |
| `.topbar`, `.context-title`, `.topbar-actions` | The sticky, blurred bar over the content |
| `.searchpill`, `.viewswitch`, `.menu`/`.menubtn`/`.menupop`/`.menuopt` | Topbar controls |
| `.card`, `.row`, `.kicker`, `.kicker-icon`, `.facts`, `.is-archived` | Records as cards or list rows. The row's first cell is the type's icon; `.facts` are a card's key fields; archived and deleted records step back with `.is-archived` |
| `.card-image` | A record's featured image across the top of its card, always 16:9 so the grid doesn't move as pictures load |
| `.dash`, `.dash-section`, `.tiles`, `.tile`, `.widgets`, `.widget`, `.widget--wide` | The dashboard: one tile per module with its count, then the cards (Coming up and the modules' widgets), `--wide` across the row |
| `.meters`, `.meter` | How much of something is used (rack units), as a bar with the number beside it |
| `.ipgrid`, `.ipcell`, `.iplegend` | A subnet's addresses, sixteen to a row: used in solid ink, reserved hatched, DHCP filled, free an outline. A used cell opens its record; a free one, for an editor, records it |
| `.secret-row`, `.secret-field` | A secret's row, whose buttons wrap under it on a phone; a form field that spans the small form |
| `.secret-value` | A secret's value in its row: a mask until Show, then the value as typed, lines kept, selectable in one click |
| `.trace`, `.trace-path`, `.trace-hop`, `.trace-link` | A cable path inside a port's row, opened from a `<details>`: each port a pill, the cables and patch panels between them in small text |
| `.empty`, `.empty--onboard`, `.pager`, `.pager-end` | Empty states and paging; `--onboard` is the first-run dashboard with the mark |
| `.modal`, `.modal--wide`, `.modal-head`, `.modal-body` | Dialogs, built on `<dialog>` |
| `[data-sortable]`, `[data-sort-item]`, `.sort-handle`, `.sort-group` | A list reordered by hand: each item's grip handle drags it (mouse, pen or touch, scrolling its pane at the edges), or moves it with ↑ and ↓ while focused. A move fires `sorted` from the list, and its listener saves the order. Settings > Modules uses it for the sidebar |
| `#confirm-modal`, `.confirm-text`, `.confirm-actions` | The one confirmation dialog, filled in from the `data-confirm` button that opened it: a question, a line saying what happens, Cancel (focused) and the action |
| `.form-grid`, `.form-wide`, `.form-check`, `.req` | The record form: two columns, long text across both, a required mark |
| `.field-head`, `.infotip`, `.infotip-pop` | A field's label with an info button beside it; the button opens the field's help in a native popover (`popovertarget`), placed under it by app.js and closed by Escape, a click elsewhere or a scroll. The input names the help in `aria-describedby` too |
| `.pickbtn` | A button standing in for a field: it opens the palette to choose a record |
| `.settings`, `.settings-nav`, `.settings-navitem`, `.settings-head`, `.settings-pane` | The settings window: a rail of sections beside the chosen one; on phones a list that slides into each section |
| `.sheet`, `.sheet-bar`, `.sheet-bar-nav`, `.sheet-article`, `.sheet-head`, `.sheet-notes`, `.prose` | The full-height detail view: Back and Forward through the records visited, then the record's actions, and close apart from them. Wider than 900px the actions head the sections' rail and close stays at the top right on its own; narrower, they share a bar across the top, close on the right. A record's notes come first in its Overview |
| `.sheet-nav`, `.tabs`, `.tab`, `.sheet-sections`, `.sheet-section`, `.sheet-section-title`, `.tab-panel` | The sheet's sections, all on the page one after another, each after the first under its own heading; the last is at least a screen tall so its heading can reach the top. Their links jump there with a smooth scroll, and the one being read is marked as the sheet scrolls. Wider than 900px the links are a rail down the sheet's left, like the settings rail, with the chosen one in `--selected` with an accent edge; the rail is added to the sheet's width, so the record's column stays 660px. Narrower, they are a row under the header that stays under the bar while the record scrolls, the marked one underlined in the accent and scrolled into view |
| `.crumbs`, `.crumbs-sep` | Where a record is: its locations, outermost first, each a link |
| `.kv`, `.kv-empty`, `.kv-long` | A record's fields: label and value in two columns, stacked on a phone |
| `.kv--edit`, `.kv-edit`, `.kv-input`, `.kv-open`, `.sheet-title-input`, `.field-error` | A record edited in place: each control reads as its value, lined up with the text, until hovered (an outline) or focused (a field); an empty one says Not set in `--faint`. `.kv-open` holds the button that opens a linked record or URL; `.field-error` is a failed save's message under its field |
| `.prose-edit`, `.prose-input`, `.kv-section` | Long text edited in place: formatted, with an Edit button that opens the Markdown; empty notes are only an Add notes button. `.kv-section` holds another module's form section in the Overview |
| `.banner`, `.banner--danger`, `.banner--stack` | A notice at the top of the sheet (archived, deleted, rack conflicts), with its action; `--stack` puts several paragraphs and buttons under each other (a backup's check, a new token) |
| `.elink` | A link to a record inside text; it opens the record's sheet in place |
| `.diagram-frame`, `.diagram-tools` | A diagram in its zoomable frame (`zoom_frame()` in macros.html, `[data-zoom]`): −, Fit and + above it on the right; zoomed in, it scrolls in a window of its own and a mouse drags it |
| `.deps-switch`, `.diagram-head` | The dependency view's List and Diagram switch (a `.seg` over `[data-views]`), and a side's heading inside a diagram |
| `.deps`, `.deptree` | The dependency view, both directions side by side, each nested; a loop and a repeat are marked, not followed |
| `.linkform`, `.mountform`, `.mountform-wide`, `.doc-actions` | Small forms inside a tab: make a link, place something in a rack, add ports, cable them, add a DNS record, record a backup run; `.mountform-wide` takes a field or a hint across the whole form (a certificate's PEM text) |
| `.module-page` | The body of a module's own page (`Page`), padded like a list |
| `.seg--links` | A segmented control whose choices are links, each a page of its own (a label size) |
| `.diagram`, `.diagram--fit`, `.diagram-scroll`, `.diagram-node`, `.diagram-link`, `.diagram-link--loose`, `.diagram-icon` | SVG drawn on the server: records as boxes that open their sheet, links as curves labeled near their lower end; a dashed link has no cable behind it. Colors come from the theme's variables, so both themes work. `--fit` scales down to the width it has; otherwise it scrolls. |
| `.labels`, `.labels--5160`, `.labels--l7160`, `.labels--62x29`, `.label`, `.label-qr` | Printable labels in real units, each size with its own named `@page`, so a sheet prints as it shows. Black on white whatever the theme |
| `.snippet` | A command to copy, in monospace and wrapped, with a Copy button (`data-copy`) under it: a backup job's report command |
| `.dropzone`, `.dropzone--slim`, `.file-thumb` | Where files are dropped or chosen, and an attachment's preview; `--slim` is one line, the featured image's empty place |
| `.gallery`, `.featured`, `.featured-actions`, `.gallery-main`, `.gallery-strip` | A record's pictures at the top of its Overview: the featured image in a box of fixed height, with Replace and Remove on it for editors, then its attached images as square tiles |
| `.lightbox`, `.lightbox-bar`, `.lightbox-img`, `.lightbox-nav` | The picture viewer: the whole window, dark in both themes, the picture fitted in it, its name and place in the bar, previous and next at the sides (at the bottom on a phone) |
| `.history`, `.changes` | Who changed what: a line per change, old value struck through, new value after |
| `.elevation`, `.rack-grid`, `.rack-u`, `.rack-slot`, `.rack-item`, `.rack-summary`, `.rack-problems` | A rack, front and rear, one grid row per unit. An empty unit is a button; overlapping items share the width, and a conflict is drawn in the danger color |
| `.palette` and its parts | The Ctrl/Cmd+K search |
| `.toast`, `.toast--error`, `.toast-action` | Confirmations under the topbar, with an optional action such as Undo |
| `.about-hero`, `.tech-stack`, `.release-list` | The About section |
| `.auth-card`, `.auth-mark`, `.flash`, `.wizard`, `.wiz-*`, `.error-code` | Sign-in, setup and error pages |
| `.ptr` | Pull to refresh on touch devices |
| `.modules-list`, `.module-icon`, `.customform` | Settings > Modules and Settings > Custom fields |

## Interface rules

- **Everyone can use it.** Every control has a name a screen reader can read
  (visible text, or `aria-label` on an icon button), every field a label.
  On a touch screen, links and small buttons in rows get at least 24 px to
  tap (the `pointer: coarse` rules in `app.css`); inside a sentence a link
  stays inline.
- **Errors are shown; success mostly isn't.** A failed action always says what
  went wrong, in a sentence, as an inline form error or an error toast. A
  success toast is for actions whose result is not already visible (a saved
  preference, a deleted record with Undo), not for every click.
- **Undo instead of "Are you sure?"** for anything recoverable. A confirmation
  dialog is kept for what can't be undone, deleting an account, and for
  deleting a record or removing a link between records, which always ask
  first (`data-confirm`) and still offer Undo after.
- **Edited where it is shown.** An editor changes a record in its Overview,
  one field at a time, saved on leaving the field; there is no Save button.
  A save that fails keeps the value, says why under the field, and holds
  the record open once. Forms are for making new things.
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
- **One way to show a record.** Every record, whatever its module, appears as
  the same card, list row and sheet, built from its type's fields. A module
  adds tabs and widgets, not a look of its own.
- **Behavior by attribute.** Templates, a module's included, get behavior
  from `app.js` through `data-*` attributes (`data-api`, `data-pick`,
  `data-then` and the rest, listed in [MODULES.md](MODULES.md#pages-tabs-and-routes)).
  Nothing ships a script of its own.
- **Conflicts are shown, not refused.** Where the real world can be
  inconsistent (two things in one rack unit), the app records it and marks it
  in the danger color, with a sidebar count, so documentation can say how
  things are before they are fixed.
- **American spelling** in everything the interface says.
