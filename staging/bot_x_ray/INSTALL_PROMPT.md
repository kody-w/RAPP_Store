Install Bot X-Ray on this computer for me. It reverse engineers Polymarket trading bots from their public trades: paste any wallet or username and it shows what the bot does, whether it was skill or luck, and whether it still works.

HOW TO WORK WITH ME
- Short sentences, everyday words. Explain any technical word the first time.
- Before each step, say in one line what you're about to do, as "Step 2 of 5".
- Run every command yourself. Only hand me a command if it needs my password or admin rights.
- If a command fails, read the error, fix the cause and retry, up to three times, then tell me plainly.
- Never ask me for passwords, API keys or logins. Don't use sudo. Don't change the app's code.
- If you can't ask me questions, use the defaults and keep going.
- Prefer a Brainstem? Install the rapplication @kody-w/bot_x_ray and say "install Bot X-Ray".

STEP 1 OF 5: CHECK THIS COMPUTER
Work out the operating system and shell. Run `node -v`. 18 or newer: carry on. Missing or older: tell me, offer the simplest install (macOS: `brew install node`, Windows: `winget install --id OpenJS.NodeJS.LTS -e`, Linux: the distro package or nvm) and wait for my yes.

STEP 2 OF 5: DOWNLOAD
Install into a folder called bot-x-ray inside the folder you're in now; the download already contains that folder.
- If ./bot-x-ray already exists, this is an update: run `node scripts/stop.js` inside it first, then download into a temporary folder and copy everything over except data/ and .env.
- macOS, Linux or Git Bash: `curl -fsSL https://part-timequant.com/kit/bot-x-ray.tar.gz | tar -xz`
- Windows PowerShell: download https://part-timequant.com/kit/bot-x-ray.zip with Invoke-WebRequest and Expand-Archive it here.

STEP 3 OF 5: TEST IT
Run `node scripts/check.js`. READY: tell me in one line what works. NOT READY: read the FAIL lines, fix the cause, run it again.

STEP 4 OF 5: SET IT UP
Skip this if it was an update. Otherwise run `node scripts/setup.js` with any answers it needs, and tell me in one line what it set.

STEP 5 OF 5: OPEN IT
Run `node scripts/launch.js`. Give me the address it prints as a link. Stop it any time with `node scripts/stop.js`.

Finish with one short, friendly message: where it's running, how to open it next time (`node scripts/launch.js`), and how to stop it.
