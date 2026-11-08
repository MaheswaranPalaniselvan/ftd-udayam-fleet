"""
Central Coordinator Client for Google Apps Script Web App.
Handles:
- Claiming next available district (atomic task lease).
- Periodic heartbeat reporting to update Google Sheet cells in real time.
- Completing tasks and triggering Telegram alerts.
- Uploading compressed .7z archives directly to Google Drive.
"""

import base64
import os
import platform
import socket
from pathlib import Path
import httpx


def get_default_machine_name() -> str:
    """Returns local hostname / computer name as the default machine identifier."""
    try:
        hostname = socket.gethostname()
        return hostname.strip() or platform.node()
    except Exception:
        return "Worker-PC"


class CentralCoordinator:
    def __init__(self, web_app_url: str, machine_name: str = None):
        self.web_app_url = web_app_url.strip() if web_app_url else ""
        self.machine_name = machine_name or get_default_machine_name()
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def close(self):
        await self.client.aclose()

    async def claim_task(self, preferred_state: str = None, preferred_district: str = None) -> dict:
        """Requests and locks the next available district from the Google Sheet."""
        if not self.web_app_url:
            return {"success": False, "message": "No central Web App URL configured."}

        params = {
            "action": "claim_task",
            "machine": self.machine_name
        }
        if preferred_state:
            params["preferred_state"] = preferred_state
        if preferred_district:
            params["preferred_district"] = preferred_district

        try:
            resp = await self.client.get(self.web_app_url, params=params)
            if resp.status_code == 200:
                return resp.json()
            return {"success": False, "message": f"Server error: {resp.status_code}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def get_fleet_status(self) -> dict:
        """Retrieves real-time status of all fleet machines and daemons from coordinator."""
        if not self.web_app_url:
            return {"status": "error", "message": "No central Web App URL configured."}

        try:
            resp = await self.client.get(self.web_app_url, params={"action": "fleet_status"})
            if resp.status_code == 200:
                return resp.json()
            return {"status": "error", "message": f"Server returned {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def send_heartbeat(
        self,
        district_code: str,
        current_record: str,
        current_dor: str,
        total_extracted: int,
        total_failed: int,
        speed_rpm: float
    ) -> bool:
        """Sends periodic progress heartbeat to update Google Sheet row in real time."""
        if not self.web_app_url:
            return False

        payload = {
            "action": "heartbeat",
            "machine": self.machine_name,
            "district_code": district_code,
            "current_record": current_record,
            "current_dor": current_dor,
            "total_extracted": total_extracted,
            "total_failed": total_failed,
            "speed_rpm": speed_rpm
        }

        try:
            resp = await self.client.post(self.web_app_url, json=payload)
            return resp.status_code == 200
        except Exception:
            return False

    async def complete_task(
        self,
        district_code: str,
        final_record: str,
        final_dor: str,
        total_extracted: int,
        total_failed: int
    ) -> bool:
        """Marks district completed in Google Sheet and notifies Telegram channel."""
        if not self.web_app_url:
            return False

        payload = {
            "action": "complete_task",
            "machine": self.machine_name,
            "district_code": district_code,
            "final_record": final_record,
            "final_dor": final_dor,
            "total_extracted": total_extracted,
            "total_failed": total_failed
        }

        try:
            resp = await self.client.post(self.web_app_url, json=payload)
            return resp.status_code == 200
        except Exception:
            return False

    async def upload_archive_to_drive(self, archive_path: Path) -> dict:
        """Uploads a compressed .7z file directly to Google Drive via Apps Script."""
        if not self.web_app_url or not archive_path.exists():
            return {"success": False, "message": "Invalid URL or archive not found"}

        with open(archive_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "action": "upload_archive",
            "filename": archive_path.name,
            "data": b64_data
        }

        try:
            resp = await self.client.post(self.web_app_url, json=payload, timeout=120.0)
            if resp.status_code == 200:
                return resp.json()
            return {"success": False, "message": f"Upload failed ({resp.status_code}): {resp.text}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
