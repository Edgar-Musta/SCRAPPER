<h1 align="center">Save Restricted Content Bot</h1>

<p align="center">
  <em>An advanced, highly optimized Telegram bot to download restricted media from private chats, featuring custom routing, batch filtering. Also added auto-forwarding support.</em>
</p>
<hr>

## ✨ Features

- **Media Extraction:** Download media from restricted chats.
- **Auto-Forwarding:** Auto-forward media bypassing the UI limit (100 messages).
- **Custom Caption:** Dynamically strip unwanted text from captions.
- **Custom Routing:** Option to route batch downloads directly to a target channel/group.
- **Media Filtering:** Grab specific media types during batch processes (e.g., only `video` or `doc`).

## 📋 Requirements

To begin using the bot, ensure you have the following:

- **Telegram Bot Token:** Get one from [@BotFather](https://t.me/BotFather).
- **API ID and Hash:** Create an application on [my.telegram.org](https://my.telegram.org) to get these.
  > **Warning**: This is an irreversible process; API ID and API Hash can only be deleted by deleting your Telegram account. Never share your credentials.
- **Session String:** Run `session-string.py` in your environment (e.g., Colab) and follow the prompts to generate your Pyrogram session string. This is used to login.
- **Bot Permissions:** When routing to a custom channel, ensure the bot is an Administrator with 'Post Messages' rights.

## ⚙️ Configuration

You can tweak the bot's performance by adjusting `config.py`:
- **`MAX_CONCURRENT_DOWNLOADS`**: Number of simultaneous downloads (default: `1`)
- **`MAX_CONCURRENT_UPLOADS`**: Number of simultaneous uploads (default: `1`)
- **`BATCH_SIZE`**: Number of posts to process in parallel during batch downloads (default: `1`)
- **`MAX_CONCURRENT_TRANSMISSIONS`**: Number of parallel connections per transfer (default: `2`). Keep in mind, higher is not always better.
- **`FLOOD_WAIT_DELAY`**: Delay in seconds between batch chunks to respect Telegram's API limits (default: `5`)

## 🚀 Deploy the Bot (Google Colab)

1. **Clone the repo:** `!git clone https://github.com/Edgar-Musta/SCRAPPER.git`
2. **Install dependencies:** `!pip install -r /content/SCRAPPER/requirements.txt`
3. **Get Session String (Login when asked):** `!python3 /content/SCRAPPER/session-string.py`
4. **Set Environment Variables:** Add your credentials to Colab Secrets, or run this in a cell:
   ```python
   import os
   os.environ["API_ID"] = "your_api_id"
   os.environ["API_HASH"] = "your_api_hash"
   os.environ["BOT_TOKEN"] = "your_bot_token"
   os.environ["SESSION_STRING"] = "your_session_string"

 5. **Start the Bot:** `!python3 /content/save-restricted-content/main.py`

## 📖 Usage & Commands

`/start` - Check if the bot is alive and view basic info.

`/help` - Show detailed instructions and command syntax.

`/batch <start_link>` - Fetch a range of posts. The bot will ask if you want to send the media to the Bot Chat or a Channel/Topic.

Filters available: Video, Photo, Audio, Doc or click ALL. You can also select multiple file types.

`/autoforward <from_chat_link>` - Auto-forward messages bypassing the UI limits (100 messages)

`/stop` - Cancel any active tasks

`/stats` - View bot stats

`/logs` - Downloads the logs.txt file

## 🤝 Credits
This project is a hard fork of [RestrictedContentDL](https://github.com/bisnuray/RestrictedContentDL) by Bisnu Ray. While built upon that foundation, this repository has been independently architected and maintained.

If you find this useful, a star is greatly appreciated. Feel free to use or share this code, with proper credits.
