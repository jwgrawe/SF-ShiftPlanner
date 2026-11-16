# Security: what the login protects, and what it doesn't (D122)

## Short version

- The **login** (D121) protects the app's *pages*. It stops another Windows
  user on the same PC from opening the administration in a browser (the app
  listens on `localhost`, which every session on that PC shares). It also
  records **who** did what in the log. Later, if the board or the app is
  opened on the internal network, the login becomes the main barrier.
- The login does **not** protect the *files*. Anyone who can read the app's
  folder can copy `data\sf_planlegger.db` and open it with any SQLite tool.
  Anyone who can change the code can switch the login off. Windows' folder
  permissions decide that, not the app.
- A folder made directly under `C:\` (such as `C:\Planlegger`) usually
  inherits **«Godkjente brukere: endre»**. That means every employee who can
  log on to that PC can read and change everything in it. Keep that in mind:
  the login is about who did what, not about keeping the files secret. For
  the pilot on one PC that's accepted. Tightening the folder is IT's job and
  comes with the proper access setup (see below).

## Decision for now: leave the folder as it is

Folder permissions on the hospital's PCs are IT's domain. Changing them
ourselves could break the app: another manager's account could no longer
start it, run `git pull` or save HR exports in `data\import`. It could also
conflict with IT's policies. So during the pilot the folder stays as Windows
made it, and the app doesn't touch it:

- Administrasjon → Tilgang → «Filene på PC-en» only **reports** which broad
  groups (Alle, Godkjente brukere, Brukere, Domenebrukere) can reach the
  files. It offers no command and changes nothing.
- Before the app is used more widely or opened on the network, we take this
  up with IT, together with the rest of the access setup (roles, a proper
  runtime, possibly a server). We may also involve the privacy officer
  (personvernombud), since absences are recorded.

### For IT, when that conversation happens (don't run this yourself)

One way to leave the folder to named accounts, the PC's administrators and
SYSTEM. It removes inheritance from `C:\`, so **every** account that starts
the app or drops files into it must be listed, or be in a group that is:

```
icacls "C:\Planlegger" /inheritance:r /grant:r "DOMENE\gruppe-eller-bruker:(OI)(CI)M" "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F"
```

To undo it: `icacls "C:\Planlegger" /reset /T` puts the inherited permissions
back. IT may well prefer their own tooling (group policy, a managed folder);
the app's check reports the result either way. BitLocker on the PC's disk
covers a stolen PC or disk.

## Why not encrypt the database?

Encryption needs a key. The app must be able to start without someone
typing a password each time, so the key would live on the same PC, in a
place the app's Windows account can read. Anyone who can read that place
can decrypt, so it amounts to the same protection as the folder permissions,
plus new ways to lose data:

- A lost key means lost data.
- Another manager's account can't open the data.
- It needs an extra package (SQLCipher) that must be installed on a locked
  PC.

Tying the key to the Windows account (DPAPI) or using Windows' own file
encryption (EFS) gives about the same result as step 2, with more moving
parts. **Folder permissions plus BitLocker** is the simple, sufficient
combination. We can revisit this if the data ever moves to a shared drive
or server.

## What counts as personal data here

- The database (names, shifts, absences, including the absence type
  «Syk», and competencies)
- `data\import\` with `arkiv\` and `avvist\`
- `data\private\` (including the anonymiser key)
- The log, which is in the database

None of it is ever committed: the repository is public (D78), and
`.gitignore` covers it. Data older than 92 days is deleted automatically
(D94).

## Tracking who did what

Every change made through the administration is logged with the name of the
logged-in administrator: imports, plans, rules, competencies, access. Each
log panel shows these entries. Logins and logouts are logged too. Changes
made while access was still open (before the first administrator was added)
show no name.
