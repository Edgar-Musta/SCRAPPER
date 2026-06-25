from os import getenv
from time import time
from dotenv import load_dotenv

load_dotenv()

class PyroConf(object):
    API_ID = int(getenv("API_ID"))
    API_HASH = getenv("API_HASH")
    BOT_TOKEN = getenv("BOT_TOKEN")
    SESSION_STRING = getenv("SESSION_STRING")
    
    OWNER_ID = int(getenv("OWNER_ID", "0"))

    BOT_START_TIME = time()
    MAX_CONCURRENT_DOWNLOADS = int(getenv("MAX_CONCURRENT_DOWNLOADS", "1"))
    MAX_CONCURRENT_UPLOADS = int(getenv("MAX_CONCURRENT_UPLOADS", "1"))
    MAX_CONCURRENT_TRANSMISSIONS = int(getenv("MAX_CONCURRENT_TRANSMISSIONS", "2"))
    BATCH_SIZE = int(getenv("BATCH_SIZE", "1"))
    FLOOD_WAIT_DELAY = int(getenv("FLOOD_WAIT_DELAY", "5"))