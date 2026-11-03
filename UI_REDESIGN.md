# Adaptive UI redesign

## Audit and direction

The original Flet 1.0.4 interface placed search and category fields on one row at
every width, used emoji as navigation/category icons, mixed fixed light colors,
and used the same tab layout on a phone and a tablet. Quantity buttons were small,
and narrow management rows competed for space with price fields and actions.

The redesign preserves the French field-sales workflow and blue app identity.
Material 3 surfaces, semantic colors, a restrained blue palette, 14 px field/button
corners, 20 px cards, 12–24 px spacing and Material icons form the shared system.
Themes follow the system initially; the toolbar switches between light and dark
for the current session. No external fonts or new dependencies are required.

Repeated article cards use a denser treatment: 14 px corners, 12 px horizontal / 8 px
vertical padding and 6–8 px gaps. Catalogue cards place the name/price beside the
quantity controls once the actual card width reaches 380 px. Narrower cards wrap
without shrinking touch targets. An odd final grid item fills the remaining row.
Basket cards combine name/subtotal and unit-price/quantity/remove controls into two
rows. Management rows put visibility, name and price on one row at 340 px and above;
hidden reset actions no longer reserve a blank column. These changes reuse the
existing fields when resizing. Article names and status labels wrap when system
text sizes increase; interactive quantity and favorite buttons keep 48 px targets.

## Productivity features

- Catalogue cards show the quantity already in the current order, including typed
  edits and undo. Their stars toggle favorites; `Tous / Favoris / Récents` scopes
  browsing. Recent means the last 20 distinct articles added to a basket, newest
  first. Favorites and recents are saved locally and respect catalogue visibility.
- With multiple visible catalogues, `Tous les catalogues` searches across them.
  Results show their origin. Active catalogue/category/search chips expose the
  scope and clear a filter directly. Short windows expose browsing modes through
  the filter button to keep the list usable.
- A compact basket button shows the live quantity and total on single-pane
  catalogue screens. The expanded layout keeps its existing basket alongside.
- Each order's menu offers duplication and reversible archiving. Duplicates retain
  prices, quantities, notes and labels, with independent photo files. Archives are
  listed separately and can be opened, reactivated or duplicated.
- Notes on orders and individual basket lines are optional. They persist across
  restarts, are copied with duplicates and appear in accounting text and photo ZIP
  summaries. Draft dialogs remain mounted during resize. The original accounting
  text format is unchanged when there are no notes.

## Complete backup and restore

Open `☰ › Sauvegarder / restaurer`. A versioned ZIP includes active and archived
orders, photos, notes, the imported catalogue, custom items/prices, visibility,
favorites and recents. The file picker determines where the ZIP is saved; there
is no automatic upload. The restore entry also appears on the first-import screen.

Before confirmation, the app validates file names, manifest version, SHA-256
hashes, JSON structure, photo references and the catalogue parser. Archives are
limited to 512 MB / 5,000 data files; traversal paths, links, duplicate filenames,
missing data and unsupported formats are rejected before storage changes.

Restoration adds imported orders and preserves existing ones. Colliding IDs get
new IDs and separate photo folders; importing the same backup again therefore
adds another independent copy. Catalogue/settings are replaced by the snapshot.
The app stages writes, retains a complete pre-restore ZIP and rolls back touched
files on an I/O error. The backup screen can export the latest recovery ZIP from
private app storage. This is a pre-restore snapshot, not an automatic deletion of
the newly imported orders. The native confirmation dialog finishes dismissing
before the application reloads.

Optional `notes`, item `note`, and `archived` fields extend existing order records.
Existing records without them remain valid. Preferences add `favorites` and
`recent`; catalogue keys and saved unit prices retain their existing meaning.

## Implementation

- `src/ui.py`: design tokens, light/dark themes, inputs, buttons, headings, cards,
  empty states and a window-layout policy. Presentation only.
- `src/main.py`: bottom navigation; optional filters; adaptive catalogue grids;
  simultaneous catalogue/photos and basket panes; redesigned management screens,
  onboarding and dialogs. Existing persistence, imports, price rules, order
  operations, exports, camera and sharing services remain in place.
- Quantity steppers have 48 logical-pixel targets and direct keyboard entry.
  Enter adds the chosen quantity. Per-order quantity drafts survive filtering.
  Basket quantities still save as they are typed; removing a line still offers undo.
- Dialogs scroll and constrain their width. Invalid article/catalogue fields show
  their existing validation messages beside the relevant input.

| Available window | Behavior |
| --- | --- |
| Compact, below 600 logical pixels | Single pane, full-width search, optional stacked filters and bottom navigation. Cards wrap controls when necessary. |
| Medium, 600–839 | Bounded single pane, grid when the actual catalogue pane has at least 680 pixels. |
| Expanded, 840 and above, at least 480 high | Catalogue or photos beside the live basket. Equal-width panes below 1200, with a centered 24-pixel gutter. Larger desktop windows use a 6:5 ratio. |
| Short, below 560 high | Secondary headings disappear; the basket summary scrolls with the order lines. |

The measured SafeArea workspace determines layout. Resize callbacks update
presentation properties and move existing controls only when the active pane or
layout mode changes. They do not reload the catalogue, recreate orders or commit
draft fields. Narrow layouts are capped at 780 pixels and expanded workspaces at
1440 pixels. Orientation is never forced. Android's safe areas and resized
keyboard viewport are respected; navigation is hidden when the keyboard is
reported open in a short window.

Flet 1.0.4 does **not** expose Android display-feature geometry or folding posture
in `PageMediaData`. The centered gutter provides clearance for the usual inner
display crease; it is not sensor-driven hinge avoidance. Devices with an occluding
or off-center hinge need native display-feature support and physical testing.

## Validation

Run the regression suite:

```powershell
python -m unittest discover -s tests -v
```

85 tests cover catalogue/import/persistence/photo behavior, resizing, notes,
favorites, recents, global search, duplication, archiving, backups and recovery.
They include storage failures, colliding order IDs, independent photo copies,
invalid hashes/catalogues, traversal rejection, cancel/confirm restore, and web
download bytes. UI assertions account for bottom navigation and management counts.

Launch an isolated preview, using only the public sample catalogue:

```powershell
python scripts/preview_ui.py
python scripts/preview_ui.py --capture
```

The capture run produces 29 PNGs under `storage/ui-preview/screenshots/`: 320 and
390 pixel outer windows; a 900 pixel inner window in both themes; basket and photo
views; 600 pixel split screen; 850×440 landscape for all three destinations;
1440 pixel desktop; article/catalogue management; an add-article dialog; expanded
filters; a reduced-height keyboard simulation; 150% typography stress on phone
and unfolded layouts; onboarding; favorites/recents/global browsing; order notes;
backup; active orders and archives; restore confirmation and the reloaded app.
Window frames reduce the actual content area slightly on Windows. The preview
resets only its own fictitious orders and settings in `storage/ui-preview/data/`.
Its restore smoke test uses a fake picker with the real native confirmation and
storage flow; it creates a recovery file inside that same isolated directory.

The screenshots were rendered with the installed Flet desktop client. The browser
connector is disabled in this environment, so mobile browser rendering has not
been visually verified. Web photo import/export is covered by the regression suite.

Before distributing an APK, check on Android hardware: fold/unfold while editing
a quantity, price and photo label; actual IME and system font/display scaling;
TalkBack focus; status/gesture insets; camera permissions and capture; Android
sharing/file pickers; split-screen rotation and device-specific hinge behavior.
No release build, package identity change, version bump or publication is included.
