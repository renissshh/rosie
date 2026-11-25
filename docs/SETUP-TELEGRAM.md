# Setting up Telegram (5 minutes, after exams)

1. In Telegram, open **@BotFather**, send `/newbot`, pick a name (e.g. "Rosie") and a
   username ending in `bot`. BotFather replies with a **token**.
2. Open `D:\Rosie\app\.env` in Notepad and add (never commit this file):

   ```text
   TELEGRAM_BOT_TOKEN=<the token from BotFather>
   ```

3. Run `.venv\Scripts\rosie telegram`, then send your bot any message from your phone.
   Rosie ignores it but prints your chat id in `D:\Rosie\logs\rosie.log`:
   `ignored a message from unknown chat 123456789 (if this is you, set TELEGRAM_CHAT_ID=...)`.
4. Add that line to `.env`, restart `rosie telegram`, and say hi.

Only that one chat is answered; everyone else gets silence. When Rosie needs a yes
(see `config/permissions.yaml`) she asks in the chat and waits 2 minutes; no answer means no.
Reminders arrive in the same chat.

With the voice extras installed (`pip install -e ".[voice]"`), you can send Rosie voice
notes: she replies with what she heard, her answer, and a voice note in her voice.
