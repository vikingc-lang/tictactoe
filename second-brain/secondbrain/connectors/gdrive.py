"""Google Drive via the Drive API (no desktop sync client needed).

Optional dependency: ``pip install google-api-python-client google-auth``.
Authenticate with a service account JSON key and share the target folder with
the service account's email address:

    [[sources]]
    name = "drive-clients"
    type = "gdrive"
    folder_id = "1AbC..."                      # from the folder URL
    credentials = "~/.secondbrain/gdrive-sa.json"

Google Docs/Sheets/Slides are exported to text/CSV/text; other files are downloaded as-is.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterator

from ..parsers import SUPPORTED_EXTS
from . import Item

EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}
FOLDER = "application/vnd.google-apps.folder"


class GoogleDriveConnector:
    def __init__(self, name: str, options: dict[str, Any]):
        self.name = name
        self.folder_id: str = options["folder_id"]
        self.credentials = os.path.expanduser(options["credentials"])
        self._service = None

    def _drive(self):
        if self._service is None:
            try:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError("gdrive sources need: pip install google-api-python-client google-auth") from exc
            creds = service_account.Credentials.from_service_account_file(
                self.credentials, scopes=["https://www.googleapis.com/auth/drive.readonly"])
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _walk(self, folder_id: str) -> Iterator[dict[str, Any]]:
        page_token = None
        while True:
            resp = self._drive().files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageToken=page_token, supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute()
            for f in resp.get("files", []):
                if f["mimeType"] == FOLDER:
                    yield from self._walk(f["id"])
                else:
                    yield f
            page_token = resp.get("nextPageToken")
            if not page_token:
                return

    def _download(self, file: dict[str, Any]) -> bytes:
        files = self._drive().files()
        if file["mimeType"] in EXPORTS:
            return files.export(fileId=file["id"], mimeType=EXPORTS[file["mimeType"]][0]).execute()
        return files.get_media(fileId=file["id"], supportsAllDrives=True).execute()

    def items(self) -> Iterator[Item]:
        for f in self._walk(self.folder_id):
            if f["mimeType"] in EXPORTS:
                ext = EXPORTS[f["mimeType"]][1]
            else:
                ext = os.path.splitext(f["name"])[1].lower()
                if ext not in SUPPORTED_EXTS:
                    continue
            modified = datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00")).timestamp()
            yield Item(uri=f"gdrive:{f['id']}", title=os.path.splitext(f["name"])[0], ext=ext,
                       modified=modified, load=lambda f=f: self._download(f))
