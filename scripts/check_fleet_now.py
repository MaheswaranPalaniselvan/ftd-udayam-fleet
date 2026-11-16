import sys
sys.path.insert(0, '.')
import asyncio
import json
from client.core.coordinator import CentralCoordinator

async def check():
    coord = CentralCoordinator()
    print(f"Connecting to coordinator at {coord.web_app_url}...")
    status = await coord.get_fleet_status()
    print("=" * 60)
    print("FLEET STATUS RESPONSE:")
    print("=" * 60)
    print(json.dumps(status, indent=2))
    await coord.close()

if __name__ == "__main__":
    asyncio.run(check())
