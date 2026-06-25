import json
import os
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

from config import PyroConf
from logger import LOGGER

SESSIONS_FILE = "user_sessions.json"

# Login conversation state per user
# { user_id: {"state": "phone"|"code"|"password", "phone": str, "hash": str, "temp_client": Client} }
LOGIN_STATES: dict = {}

# Fully started, ready-to-use clients indexed by Telegram user ID
USER_CLIENTS: dict[int, Client] = {}


# ─── Persistence ─────────────────────────────────────────────────────────────

def _load_sessions() -> dict:
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_sessions(data: dict):
    with open(SESSIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─── Client factory ──────────────────────────────────────────────────────────

def _build_client(user_id: int, session_string: str) -> Client:
    return Client(
        name=f"user_{user_id}",
        api_id=PyroConf.API_ID,
        api_hash=PyroConf.API_HASH,
        session_string=session_string,
        in_memory=True,
        workers=10,
        max_concurrent_transmissions=PyroConf.MAX_CONCURRENT_TRANSMISSIONS,
        sleep_threshold=60,
    )


# ─── Lifecycle ───────────────────────────────────────────────────────────────

async def start_saved_clients():
    """Start a client for every persisted session. Call on bot startup."""
    for uid_str, session_string in _load_sessions().items():
        uid = int(uid_str)
        try:
            client = _build_client(uid, session_string)
            await client.start()
            USER_CLIENTS[uid] = client
            LOGGER(__name__).info(f"Restored session for user {uid}")
        except Exception as e:
            LOGGER(__name__).warning(f"Could not restore session for user {uid}: {e}")


async def stop_all_clients():
    """Stop all user clients. Call on bot shutdown."""
    for client in list(USER_CLIENTS.values()):
        try:
            await client.stop()
        except Exception:
            pass
    USER_CLIENTS.clear()


def get_user_client(user_id: int) -> Client | None:
    return USER_CLIENTS.get(user_id)


# ─── Login flow ──────────────────────────────────────────────────────────────

def start_login_flow(user_id: int):
    """Put the user into the 'waiting for phone number' state."""
    LOGIN_STATES[user_id] = {"state": "phone"}


async def process_phone(user_id: int, phone: str):
    """
    Create a temp client and send the OTP.
    Stores state and returns "code".
    """
    temp_client = Client(
        name=f"login_{user_id}",
        api_id=PyroConf.API_ID,
        api_hash=PyroConf.API_HASH,
        in_memory=True,
    )
    await temp_client.connect()
    sent = await temp_client.send_code(phone)
    LOGIN_STATES[user_id] = {
        "state": "code",
        "phone": phone,
        "hash": sent.phone_code_hash,
        "temp_client": temp_client,
    }
    return "code"


async def process_code(user_id: int, code: str) -> str:
    """
    Verify the OTP code.
    Returns "done" on success or "password" if 2FA is required.
    Raises PhoneCodeInvalid / PhoneCodeExpired on bad input.
    """
    state = LOGIN_STATES.get(user_id)
    if not state or state["state"] != "code":
        raise ValueError("Not currently waiting for a code.")

    client = state["temp_client"]
    try:
        await client.sign_in(state["phone"], state["hash"], code)
        return await _finalize_login(user_id, client)
    except SessionPasswordNeeded:
        state["state"] = "password"
        return "password"


async def process_password(user_id: int, password: str) -> str:
    """
    Verify the 2FA password.
    Returns "done" on success. Raises an error on wrong password.
    """
    state = LOGIN_STATES.get(user_id)
    if not state or state["state"] != "password":
        raise ValueError("Not currently waiting for a password.")

    client = state["temp_client"]
    await client.check_password(password)
    return await _finalize_login(user_id, client)


async def _finalize_login(user_id: int, temp_client: Client) -> str:
    """Export session string, persist it, and start a permanent client."""
    session_string = await temp_client.export_session_string()
    await temp_client.disconnect()
    LOGIN_STATES.pop(user_id, None)

    sessions = _load_sessions()
    sessions[str(user_id)] = session_string
    _save_sessions(sessions)

    client = _build_client(user_id, session_string)
    await client.start()
    USER_CLIENTS[user_id] = client
    return "done"


async def cancel_login(user_id: int):
    """Abort an in-progress login flow and disconnect the temp client."""
    state = LOGIN_STATES.pop(user_id, None)
    if state and "temp_client" in state:
        try:
            await state["temp_client"].disconnect()
        except Exception:
            pass


async def logout_user(user_id: int):
    """Revoke the user's session and remove it from storage."""
    await cancel_login(user_id)
    client = USER_CLIENTS.pop(user_id, None)
    if client:
        try:
            await client.log_out()
        except Exception:
            try:
                await client.stop()
            except Exception:
                pass

    sessions = _load_sessions()
    sessions.pop(str(user_id), None)
    _save_sessions(sessions)


# ─── State helpers ────────────────────────────────────────────────────────────

def is_logging_in(user_id: int) -> bool:
    return user_id in LOGIN_STATES


def get_login_state(user_id: int) -> str | None:
    s = LOGIN_STATES.get(user_id)
    return s["state"] if s else None
