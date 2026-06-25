import re
from pyrogram.utils import get_channel_id
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

PREFIX_NUM_UNDERSCORE_RE = re.compile(r'^\d+_')


def is_private_link(link: str) -> bool:
    """Return True if the link points to a private channel/group.

    Private links contain '/c/' in their path:
        https://t.me/c/1234567890/42          ← private channel
        https://t.me/c/1234567890/10/42       ← private channel with topic

    Public links use a username:
        https://t.me/somechannel/42           ← public channel
        https://t.me/somechannel/10/42        ← public channel with topic
    """
    if not link:
        return False
    clean = link.split("?")[0].rstrip("/")
    parts = clean.split("/")
    # parts[3] is the segment after 't.me/' — 'c' means private
    return len(parts) >= 5 and parts[3] == "c"
PREFIX_NUM_LETTER_RE = re.compile(r'^(\d+)\s*([a-zA-Z])')
PREFIX_NUM_SPACE_RE = re.compile(r'^\d+ ')

def clean_caption(caption: str) -> str:
    if not caption:
        return ""

    caption = re.sub(r'(?<!href=["\'])@([a-zA-Z0-9_]+)', r'(at)\1', caption)
    
    def defang_bare_link(match):
        url = match.group(0)
        if re.search(r'(?:t\.me|telegram\.me)/.+/\d+', url, re.IGNORECASE):
            return url 
        return url.replace('.', '(dot)')
        
    pattern = r'(?<!href=["\'])(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|chat\.whatsapp\.com)\S+'
    caption = re.sub(pattern, defang_bare_link, caption, flags=re.IGNORECASE)
    
    return caption.strip()

def apply_caption_rules(caption: str, rules: list) -> str:
    if not caption: 
        return ""
    
    for rule in rules:
        if rule == "keep": 
            continue

        lines = caption.replace('\r', '').split('\n')
        
        if rule == "rm_last":
            target_idx = -1
            for i in range(len(lines) - 1, -1, -1):
                clean_line = re.sub(r'<[^>]+>', '', lines[i])
                if re.search(r'[a-zA-Z0-9]', clean_line):
                    target_idx = i
                    break
            
            if target_idx != -1:
                kept_lines = lines[:target_idx]
                dangling_tags = ""
                for j in range(target_idx, len(lines)):
                    tags = re.findall(r'</[^>]+>', lines[j])
                    if tags:
                        dangling_tags += "".join(tags)
                
                caption = '\n'.join(kept_lines).strip() + dangling_tags
            else:
                caption = ""

        elif rule.startswith("remove_text:"):
            text_to_remove = rule.split("remove_text:", 1)[1]

            caption = caption.replace(text_to_remove, "")
            if text_to_remove.startswith("@"):
                alt_text = text_to_remove.replace("@", "(at)", 1)
                caption = caption.replace(alt_text, "")

            caption = re.sub(r'[ \t]{2,}', ' ', caption)
            caption = re.sub(r' \.', '.', caption)
            caption = re.sub(r'\n[ \t]+\n', '\n\n', caption)
            caption = caption.strip()

    return caption.strip()

def extract_youtube_keyboard(reply_markup) -> InlineKeyboardMarkup | None:
    if not reply_markup or not hasattr(reply_markup, 'inline_keyboard'):
        return None

    valid_buttons = []
    yt_domains = ("youtube.com", "youtu.be")

    for row in reply_markup.inline_keyboard:
        new_row = []
        for button in row:
            if button.url:
                if any(domain in button.url.lower() for domain in yt_domains):
                    new_row.append(InlineKeyboardButton(text=button.text, url=button.url))
        if new_row:
            valid_buttons.append(new_row)

    if valid_buttons:
        return InlineKeyboardMarkup(valid_buttons)
    return None

async def get_parsed_msg(chat_msg):

    if chat_msg.caption:
        return chat_msg.caption.html
    elif chat_msg.text:
        return chat_msg.text.html
    return ""
    
def getChatMsgID(link: str):
    if "?" in link:
        link = link.split("?")[0]

    link = link.rstrip("/")

    linkps = link.split("/")
    chat_id, message_thread_id, message_id = None, None, None
    
    try:
        if len(linkps) == 7 and linkps[3] == "c":
            chat_id = get_channel_id(int(linkps[4]))
            message_thread_id = int(linkps[5])
            message_id = int(linkps[6])
        elif len(linkps) == 6:
            if linkps[3] == "c":
                chat_id = get_channel_id(int(linkps[4]))
                message_id = int(linkps[5])
            else:
                chat_id = linkps[3]
                message_thread_id = int(linkps[4])
                message_id = int(linkps[5])
        elif len(linkps) == 5:
            chat_id = linkps[3]
            if chat_id == "m":
                raise ValueError("Invalid ClientType used to parse this message link")
            message_id = int(linkps[4])
    except (ValueError, TypeError):
        raise ValueError("Invalid post URL. Must end with a numeric ID.")

    if not chat_id or not message_id:
        raise ValueError("Please send a valid Telegram post URL.")

    return chat_id, message_id, message_thread_id

def get_file_name(message_id: int, chat_message) -> str:
    def clean_name(name):
        if not name:
            return ""

        name = PREFIX_NUM_UNDERSCORE_RE.sub('', name)
        name = name.replace('_', ' ')

        match = PREFIX_NUM_LETTER_RE.match(name)
        if match:
            prefix_num = match.group(1)
            rest_of_text = name[len(match.group(0))-1:] 
            name = f"{prefix_num}) {rest_of_text}"

        if PREFIX_NUM_SPACE_RE.match(name) and not name.startswith(f"{name.split(' ')[0]})"):
            parts = name.split(' ', 1)
            if len(parts) > 1:
                name = f"{parts[0]}) {parts[1]}"
            
        return name

    filename = ""

    if chat_message.document:
        filename = chat_message.document.file_name
    elif chat_message.video:
        filename = chat_message.video.file_name or f"{message_id}.mp4"
    elif chat_message.audio:
        filename = chat_message.audio.file_name or f"{message_id}.mp3"
    elif chat_message.voice:
        filename = f"{message_id}.ogg"
    elif chat_message.video_note:
        filename = f"{message_id}.mp4"
    elif chat_message.animation:
        filename = chat_message.animation.file_name or f"{message_id}.gif"
    elif chat_message.sticker:
        if chat_message.sticker.is_animated:
            filename = f"{message_id}.tgs"
        elif chat_message.sticker.is_video:
            filename = f"{message_id}.webm"
        else:
            filename = f"{message_id}.webp"
    elif chat_message.photo:
        filename = f"{message_id}.jpg"
    
    final_name = clean_name(filename)

    if not final_name or final_name.strip() == "":
        return str(message_id)

    return final_name