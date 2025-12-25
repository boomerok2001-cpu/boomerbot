import asyncio
import aiohttp

DATA_API = "https://data-api.polymarket.com"
WALLET = "0xF734740627733Bda64fe6a69f81caBA96e3d7382"

async def check_wallet_activity():
    async with aiohttp.ClientSession() as session:
        print(f"Checking wallet: {WALLET}")
        
        # 1. Check as Maker
        print("\n--- Checking as Maker (maker_address) ---")
        try:
            async with session.get(f"{DATA_API}/trades", params={"maker_address": WALLET, "limit": 5}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Maker trades found: {len(data)}")
                    if data: print(f"Sample: {data[0].get('side')} {data[0].get('size')} shares")
                else:
                    print(f"Error: {resp.status}")
        except Exception as e:
            print(e)
            
        # 2. Check as Taker (taker_address) - if supported
        print("\n--- Checking as Taker (taker_address) ---")
        try:
            async with session.get(f"{DATA_API}/trades", params={"taker_address": WALLET, "limit": 5}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Taker trades found: {len(data)}")
                    if data: print(f"Sample: {data[0].get('side')} {data[0].get('size')} shares")
                else:
                    print(f"Error {resp.status}: {await resp.text()}")
        except Exception as e:
            print(e)

        # 3. Check generic 'user' param (might cover both)
        print("\n--- Checking as User (user) ---")
        try:
            async with session.get(f"{DATA_API}/trades", params={"user": WALLET, "limit": 5}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"User trades found: {len(data)}")
                    if data: print(f"Sample: {data[0].get('side')} {data[0].get('size')} shares")
                else:
                    print(f"Error {resp.status}: {await resp.text()}")
        except Exception as e:
            print(e)

if __name__ == "__main__":
    asyncio.run(check_wallet_activity())
