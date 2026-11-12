# The public board and the admin screens on one PC

Recommendation, round 13 (2026-11-12). **Round 14:** layers 1 and 2 are built
(D120: `python run.py --tavle`, and the board lock). Layer 3 becomes a login
with the Buypass ID card, one account per manager (assessment in
[smart-card-login.md](smart-card-login.md), Q53).

## The situation

- The app runs on one PC and listens on that PC only (`127.0.0.1`). Nothing
  is reachable from the network, which is good and should stay so until IT
  approves anything else.
- The board («tavlen», `/display`) is public: names, where each person
  works, rotation times, «Diverse info». Everything else (planning, sources,
  competencies, rules, fritak, statistics) is for admins only.
- The big screen would be a second monitor on the same PC.

The risk is the one you describe: an admin page ends up on the big screen
(a window dragged across, a link clicked in the board window, the screen set
to *duplicate*), or someone walks up to an unlocked admin screen.

## Recommended setup: three layers, no network change

### 1. The board gets its own locked-down window

`python run.py` also opens the board in **kiosk mode** on the second screen,
using the browser already on the PC (Edge or Chrome):

- full screen, no address bar, no tabs, no menus: nothing to click into;
- its **own browser profile**, so it never shares a login with the admin
  browser;
- placed on the second screen automatically.

### 2. The board window can only ever show the board

The kiosk window identifies itself to the app as «tavle». From then on the
app answers any other page request from that window by sending it back to the
board. Even if someone manages to type an address or click a link there, it
cannot show an admin page. This is enforced by the app, not by people
remembering.

### 3. Admin pages need a PIN

Everything except the board asks for a PIN (D25 already allows PIN level).
The admin session locks itself after inactivity (e.g. 15 minutes), and a
«Lås» button locks it at once. That covers the walk-up risk. It also means a
board window that somehow left the board would meet a PIN prompt, not data.

### Plus three habits (a one-page note next to the PC)

- Windows display setting: **Extend**, never *Duplicate*; the desk monitor
  is the *main display*, so new windows open there.
- Never move a window to the big screen; if the board looks wrong, restart
  the app rather than fiddling with the window.
- Lock the admin session («Lås», or Windows+L) when leaving the PC.

### And one rule in the code

The board shows **only** names, placements, times and «Diverse info» — never
alerts, absences, competencies, fritak or statistics (extends D46). A test
guards it, so a later change can't leak something onto the board by accident.

## Later, when IT allows

A separate small device (mini PC or a screen's built-in browser) shows the
board over the network with a read-only key, and the admin PC can be anywhere.
The app would then open *only* the board to the network. The layers above
still apply. This needs IT approval, so it isn't the first step.

## Size

Layers 1–3 and the board test: a small round of work. The PIN is the part
with decisions in it: one shared admin PIN or one per manager (per-manager
gives the log a name), and the inactivity time.
