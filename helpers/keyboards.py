from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Download Single", callback_data="menu_single"),
         InlineKeyboardButton("📦 Start Batch Here", callback_data="menu_batch")],
        [InlineKeyboardButton("⏩ Auto-forward Here", callback_data="menu_auto")]
    ])

def get_caption_keyboard(message_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✂️ Trim Last Line", callback_data=f"cap_rmlast_{message_id}"),
         InlineKeyboardButton("✅ Start", callback_data=f"cap_done_{message_id}")]
    ])

def get_filter_keyboard(selected_filters, message_id):
    filters = ["video", "photo", "audio", "doc"]
    
    if len(selected_filters) >= 4:
        selected_filters = [] 
        
    buttons = []
    for f in filters:
        text = f"✅ {f.title()}" if f in selected_filters else f.title()
        buttons.append(InlineKeyboardButton(text, callback_data=f"filter_{f}_{message_id}"))

    if not selected_filters:
        bottom_button = InlineKeyboardButton("✅ All", callback_data=f"filter_all_{message_id}")
    else:
        bottom_button = InlineKeyboardButton("➡️ Continue", callback_data=f"filter_done_{message_id}")
        
    return InlineKeyboardMarkup([
        buttons[:2], 
        buttons[2:], 
        [bottom_button] 
    ])