# Login and access (D121)

Built in round 15 (2026-11-13). Replaces the card-login plan in
[smart-card-login.md](smart-card-login.md): since everyone is always logged
into Windows with their ID card, the app uses that login instead of talking
to the card itself.

## How it works

- **The board is always public** (`/display`, and the kiosk window).
- **Everything else needs an administrator**, once at least one has been
  added. Until then the app is open, as before, with a yellow banner saying
  so, so updating can't lock anyone out.
- **Identity = the Windows login.** When a page needs a login, the browser is
  asked to prove which Windows user is running it (Windows single sign-on,
  «Negotiate», the same mechanism intranet sites use). Windows checks the
  proof itself. Nobody types anything: the next page simply opens, logged in.
  The ID card is what got the person into Windows, so it is part of the chain.
- **A session per browser**, ended by «Logg ut», by an hour of inactivity, or
  when the app restarts. A new login is automatic.
- **Every logged action records who did it** (the log's new «hvem» column;
  «system» for what the app does by itself, like imports).

## Root mode: the owner's way in

`python run.py --rotadmin` starts the app and opens the browser with a
**one-time key** that makes *that* browser root for this run (marked
ROTMODUS). Only root can add or remove administrators and change the login
method (Administrasjon → Tilgang). Anyone who can start the app can already
reach its files, so root mode gives nothing new to such a person — but no
other browser and no other user on the PC can use it. The key works once.

Administrators are Windows accounts: `DOMENE\brukernavn`, or just
`brukernavn` to match it in any domain.

## Two login methods

| Method | When | Note |
|---|---|---|
| **Windows-innlogging** (default) | Normal use | The browser proves the Windows user. Works even if several people are logged into the same PC. |
| **Windows-brukeren som startet appen** | Fallback, if the browser isn't allowed to send the Windows login | Everyone using that Windows session counts as whoever started the app. Fine for a personal session, weak for a shared one. |

## To check on the hospital PC (I can't test Windows here)

1. `python run.py --test-innlogging` — runs a complete Windows sign-on
   inside the app and prints the user name Windows confirms, or why it
   failed. Send me the output (only your Windows user name).
2. Start the app normally and open **`http://localhost:8000`** (run.py now
   opens that address). Browsers share the Windows login only with addresses
   they consider internal; `localhost` is, `127.0.0.1` may not be. If a page
   «Logger inn …» stays up, IT can add `localhost` to «Lokalt intranett» — or
   switch to the fallback method in root mode.
3. `python run.py --rotadmin`, add yourself under Tilgang (your
   `DOMENE\brukernavn` — the Tilgang page shows the account the app runs as),
   then the other managers.

## Things to know

- **Taking the card out** locks Windows (if the hospital's usual policy is
  set), which also locks the browser with it. The app's own session ends after
  an hour without use, or at «Logg ut».
- **The app runs as one Windows user.** If that person logs off, the app and
  the board stop. See Q54.
- Sessions are kept in memory only; nothing about logins is stored except
  each administrator's last login time.
