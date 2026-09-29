# Getting started on your computer

This takes about 10 minutes. Everything runs on your machine, and your files stay where they are.
The brain reads them but never moves or changes them.

## Fastest way: the single HTML file (no install)

1. Download **`second-brain.html`** (in the `second-brain` folder, or ask for the file directly) and save it
   somewhere permanent, such as `Documents/SecondBrain/second-brain.html`.
2. Double-click it. It opens in your browser. **Chrome or Edge are recommended**, because folders you add
   there keep updating automatically.
3. Go to **🔌 Sources & settings → 📁 Add a folder…**, pick a folder (Documents, OneDrive, Dropbox, Google
   Drive, and so on), and allow the browser to view it. You can also drag files onto the page.
4. Emails: drop `.eml` files or a `.mbox` archive (Gmail → takeout.google.com → Mail) onto the page. Each
   email and its attachments become searchable and linked.
5. Paste your Claude API key under **Claude connection** to get written answers, documents and decks.
6. Use Ask, Search, Library, Connections, Create and Remember.

Your brain is saved inside that browser. Open the **same file in the same browser** to find it again. When you
reopen it, click **Reconnect folders** if asked, so the browser can re-read your folders and pick up changes.
Use **Export backup** to keep a copy or to move to another computer.

You want the full Python app below if you need the brain available to Claude Desktop (MCP), a REST API
for other tools, or always-on background syncing.

---

## 1. Install Python (one time)

You need **Python 3.11 or newer**.

- **Windows:** download it from <https://www.python.org/downloads/>. In the installer, tick
  **"Add python.exe to PATH"**, then click *Install Now*.
- **Mac:** download the macOS installer from <https://www.python.org/downloads/> and run it.
  The `python3` that ships with macOS is too old.

To check, open Terminal (Mac) or PowerShell (Windows) and run `python3 --version` (Windows: `py --version`).

## 2. Download Second Brain

**Option A (no Git):** open <https://github.com/vikingc-lang/tictactoe/tree/claude/epic-darwin-cys58u>,
click **Code → Download ZIP**, and unzip it. The app is in the `second-brain` folder. You can move that
folder anywhere, for example `Documents/SecondBrain`.

**Option B (Git):**
```bash
git clone -b claude/epic-darwin-cys58u https://github.com/vikingc-lang/tictactoe.git
cd tictactoe/second-brain
```

## 3. Start it

| Windows | Mac |
|---|---|
| Double-click **`Start Second Brain.bat`** | Right-click **`Start Second Brain.command`** → **Open** (the first time only, to get past Gatekeeper) |

The first start sets up a private Python environment inside the folder, which takes about a minute.
Your browser then opens at **http://localhost:8787**. Keep the small terminal window open while you use
the app, and close it to stop.

> If macOS says the file isn't executable, open Terminal in that folder and run
> `chmod +x "Start Second Brain.command"`, then double-click it again.

## 4. Connect your folders

In the app, go to **🔌 Sources & settings → Add a source**:

1. **Type:** *Folder on this computer*
2. **Name:** anything, e.g. `Clients`
3. **Folder path:** paste the path. Some examples:

| What | Windows | Mac |
|---|---|---|
| Documents | `C:\Users\<you>\Documents` | `/Users/<you>/Documents` |
| OneDrive / SharePoint | `C:\Users\<you>\OneDrive - <Company>\Clients` | `/Users/<you>/Library/CloudStorage/OneDrive-<Company>/Clients` |
| Dropbox | `C:\Users\<you>\Dropbox` | `/Users/<you>/Library/CloudStorage/Dropbox` |
| Google Drive (desktop app) | `G:\My Drive` | `/Users/<you>/Library/CloudStorage/GoogleDrive-<email>/My Drive` |
| iCloud Drive | `C:\Users\<you>\iCloudDrive` | `/Users/<you>/Library/Mobile Documents/com~apple~CloudDocs` |
| Obsidian vault | wherever your vault lives | wherever your vault lives |
| External / NAS drive | `E:\Archive` or `\\nas\share\projects` | `/Volumes/Archive` |

**Tip for copying a path:** on Windows, Shift + right-click the folder → **Copy as path**. On Mac, right-click
the folder, hold **Option**, then choose **Copy "…" as Pathname**.

Click **Add & sync**. A banner shows progress. The first sync of a large folder can take a few minutes,
and after that only changes are processed. Repeat for each place your knowledge lives.

**Start focused.** Begin with one or two folders you actually use, such as current clients and your
playbooks. You get better answers from good material than from everything at once.

## 4b. Connect your email (optional)

Each email becomes searchable, and **each attachment becomes its own document** (PDF, Word, Excel,
PowerPoint), linked back to the email it came with. Nothing is marked as read, and nothing is sent or deleted.

**In the app:** go to **Sources & settings → Add a source → Email mailbox**, then enter your email address
and an **app password**. The server and folders are filled in for Gmail, iCloud and Yahoo. The app checks
the sign-in before saving, and the password is stored only on your computer.

| Provider | Where to create an app password |
|---|---|
| Gmail | myaccount.google.com/apppasswords (2-step verification must be on). Use folders `INBOX, [Gmail]/Sent Mail`. |
| iCloud | appleid.apple.com → Sign-In and Security → App-Specific Passwords |
| Yahoo | Account security → Generate app password |
| Outlook / Microsoft 365 | Most company accounts block password sign-in, so save the emails you care about into a folder (drag them out of Outlook, or use *Save As*) and add that folder. For Outlook `.msg` files, run `pip install extract-msg` once. |

**Saved emails and archives also work** in any folder you add: `.eml` files, Outlook `.msg` files, and
`.mbox` archives. For example, download your whole Gmail from takeout.google.com → Mail and drop the
`.mbox` into a folder.

**Tip:** start with a year of mail (the default *Days back* is 365), or narrow it to a client with a
search such as `FROM "acme.com"` in `brain.toml`.

## 5. Connect Claude (for written answers, documents and decks)

1. Create an API key at <https://console.anthropic.com> (Settings → API keys).
2. In the app, open **Sources & settings → Claude connection**, paste the key and click **Save key**.

The key is stored only on your computer, in `~/.secondbrain/secrets.env`. Without a key you can still
search, browse and see connections.

Optionally, click **🧩 Summarise & connect documents with Claude**. It adds summaries and tags, and links
documents that mention the same people and companies. Each click processes 20 documents and uses API credits.

## 6. Use it

| Tab | What to do |
|---|---|
| 💬 **Ask** | Ask questions in plain English. Answers cite your documents: click a `[1]` to open the source. |
| 🔎 **Search** | Keyword search, including text inside Word, PowerPoint and PDF files. |
| 📚 **Library** | Everything indexed. Click a document to see its summary and connected documents, or open the original file. |
| 🕸️ **Connections** | A visual map of how your knowledge links together. |
| ✨ **Create** | Generate a Word brief, a PowerPoint deck or Markdown on any topic. Click **Download** when it's done. The brain also learns from what it creates. |
| 📝 **Remember…** | Capture a fact, decision or meeting note. Write `[[Document Title]]` to link it to a document. |

The brain **keeps learning while the app is open**: it re-checks your folders every minute and picks up
new, edited and deleted files.

## 7. Optional extras

- **Use your firm's branding:** in `~/.secondbrain/brain.toml`, set
  `deck_template = "C:/Templates/firm-master.pptx"` and/or `doc_template = ".../letterhead.docx"`.
- **Use it inside Claude Desktop:** see *Use it from Claude (MCP)* in [README.md](README.md). On Windows, the
  command is `<folder>\.venv\Scripts\python.exe` with args `["-m", "secondbrain", "mcp"]`. On Mac, it's
  `<folder>/.venv/bin/python` with the same args.
- **Web pages and APIs:** add them under *Add a source*, or edit `brain.toml` (see `brain.example.toml`).
- **Command line:** everything in the app is also available as `brain …` commands (see README).

## Troubleshooting

| Problem | Fix |
|---|---|
| "Python 3.11 or newer is required" | Install Python from python.org (step 1), then start again. |
| Browser didn't open | Go to <http://localhost:8787> yourself. |
| "folder not found on this computer" | Check the path. For OneDrive, make sure the folder is set to *Always keep on this device*, or at least synced. |
| Some files show "issues" on the Sources page | They are usually password-protected or corrupt files. Everything else still indexes. |
| Port 8787 is busy | Run `.venv/bin/python -m secondbrain ui --port 8790` (Windows: `.venv\Scripts\python -m secondbrain ui --port 8790`). |
| Start over | Close the app and delete the `~/.secondbrain` folder. Your own files are never touched. |
