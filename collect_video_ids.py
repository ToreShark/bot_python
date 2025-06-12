from telethon import TelegramClient
import os
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")

CHANNEL_ID = -1002275474152      # ваш закрытый канал

client = TelegramClient("bankruptcy", api_id, api_hash)

async def main():
    async for msg in client.iter_messages(CHANNEL_ID):
        if msg.video:
            print(f"https://t.me/c/2275474152/{msg.id}")

with client:
    client.loop.run_until_complete(main())
