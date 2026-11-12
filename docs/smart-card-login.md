# Logging in with the Buypass ID card: assessment

Round 14 (2026-11-12). Assessment of the proposal from a separate research
session (local challenge–response against the card through Windows' own
smart-card support). Nothing is built yet (Q53).

## Verdict

**Go-ahead, with the adjustments below.** It is a good fit:

- strong identity with no passwords to manage, and per-manager accounts (your
  choice) come for free;
- nothing to install for the card: Windows already handles it
  (Microsoft Class Minidriver, CNG), so no OpenSC/PKCS#11;
- fully local, so no network change is needed (in line with D49/D61).

## How it would work

1. A manager clicks «Logg inn med kort» in the admin browser.
2. The app (the Python program on the same PC) finds the Buypass
   *authentication* certificate in the Windows certificate store, makes a
   random 32-byte challenge and asks Windows to sign it with the card's key.
3. Windows shows its own PIN dialog. The PIN never passes through the app.
4. The app checks the signature against the certificate. If it matches, the
   card is present and the PIN was right. The browser gets a session for that
   manager, and the log records their name from then on.
5. **Pulling the card out logs out at once** (the app watches the reader). An
   inactivity timeout is the backup.

## Adjustments to the summary

| # | Point | Why |
|---|---|---|
| 1 | Use **only the authentication certificate** (Extended Key Usage *Client Authentication*, key usage *digitalSignature*), and **never** one with *nonRepudiation*. | Buypass cards also carry a signing certificate. Its key can make legally binding (qualified) e-signatures and often has its own PIN. A login must never use it. |
| 2 | Key accounts on the **certificate** (its fingerprint, or the Buypass-assigned serial number in the subject), not on the name. | Names change and repeat. The subject serial number is Buypass's ID, not the employee number, so map it once at enrolment. |
| 3 | **Enrolment**: the first card that logs in becomes the owner; the owner approves each new card holder once. | Otherwise anyone at the hospital with a Buypass card could log in. |
| 4 | Check the **validity dates** and the **chain to a Buypass root** in the Windows trust store. Check **revocation** when the network allows it, without locking everyone out when it doesn't. | Revocation (CRL/OCSP) needs the network. Fail-closed would stop the app when offline. Possession of card + PIN is the main proof. |
| 5 | Handle the card's own error codes: cancelled (`SCARD_W_CANCELLED_BY_USER`), wrong PIN (`SCARD_W_WRONG_CHV`), **PIN blocked** (`SCARD_W_CHV_BLOCKED` → «contact Buypass/IT»), card removed, no reader. Not just a generic failure. | Clear messages instead of «login failed». |
| 6 | Support both **RSA** (PKCS#1 v1.5 / PSS) and **EC** keys when signing and verifying. | Which one a card uses varies by card generation. |
| 7 | The app must run as the **logged-in Windows user** (as `python run.py` does), not as a Windows service. | The PIN dialog appears on that user's desktop. |
| 8 | **Break-glass**: a few one-time recovery codes for the owner, printed and kept sealed. | If the reader or a card fails, someone must still be able to get in. |
| 9 | Dependencies: Windows APIs through `ctypes` (built into Python) plus the `cryptography` package for reading and checking certificates (`pip install --user`, as D48). No `pywin32`. | Smallest footprint that does the job. |

## Testing (needs you once)

I can't run Windows card APIs in this development environment. So:

- the login is built behind an interface, with a stand-in for the demo and
  the tests, so everything around it is tested here;
- a check command, `python run.py --test-kort`, run once on the hospital PC
  with a card in the reader, lists the certificates it finds (issuer and key
  usage only, names masked), does a sign-and-verify round trip, and prints
  OK or what failed. You send me that output; it contains no personal data.

## Order of work

1. Accounts, sessions, login page; everything except the board needs a login;
   names in the log. (The demo keeps a simple stand-in login.)
2. Card login, enrolment, `--test-kort`.
3. Logout on card removal, plus inactivity timeout.
4. Recovery codes.

The board window (D120) never has a session, and it is already locked to the
board.

## Questions for you (Q53)

1. **Windows login on that PC:** does each manager log into Windows with their
   own card, or is it a shared login that stays signed in? If each manager
   has their own Windows session, the app could simply trust that session,
   which is even simpler. If it's shared, the card login above is the way.
2. **Who is the first owner** (the one who approves the others)?
3. Is a **card reader** fitted to that PC, or does it need one?
