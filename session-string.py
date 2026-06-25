import asyncio
from pyrogram import Client

async def main():
    print("\n" + "="*50)
    print("🤖 Save Restricted Content Bot - Session Generator")
    print("="*50 + "\n")
    print("You can get your API ID and API HASH from https://my.telegram.org/\n")

    while True:
        api_id_str = input("Enter your API ID: ").strip()
        try:
            api_id = int(api_id_str)
            break
        except ValueError:
            print("❌ API ID must be a number. Please try again.")

    api_hash = input("Enter your API HASH: ").strip()

    print("\n" + "="*50)
    print("⚠️ IMPORTANT: When prompted for your phone number,")
    print("you MUST enter it in international format starting")
    print("with a '+' sign and your country code.")
    print("Example for India: +919876543210")
    print("="*50 + "\n")

    try:
        async with Client(
            name="session",
            api_id=api_id,
            api_hash=api_hash,
            in_memory=True
        ) as app:
            session = await app.export_session_string()
            print("\n✅ Authentication Successful!\n")
            print("👇 YOUR SESSION STRING 👇\n")
            print(session)
            print("\n⚠️ Keep this string safe and NEVER share it with anyone!")

    except Exception as e:
        print(f"\n❌ An error occurred during authentication: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSession generation cancelled by user.")
