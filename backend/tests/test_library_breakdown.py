from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.db import open_database_connection
from app.services.library_service import LibraryService
from test_app import FakeObjectStore
from test_library_team import _app, _personal_headers, _settings, _upload


def test_breakdown_covers_all_files_reservations_expiry_delete_and_gc(tmp_path):
    settings, store = _settings(tmp_path), FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        headers = _personal_headers(client, settings, "storage_owner", "storage@example.com")
        files = [
            _upload(client, store, headers, name=f"file-{i}.md", content=b"123")[0]
            for i in range(101)
        ]
        image = BytesIO()
        Image.new("RGB", (1, 1)).save(image, format="PNG")
        image_bytes = image.getvalue()
        _upload(client, store, headers, name="picture.png", content=image_bytes,
                mime_type="image/png")
        temporary = client.post(
            "/api/v1/library/files/upload-url", headers=headers,
            json={"fileName": "temporary.md", "fileSizeBytes": 4, "mimeType": "text/markdown"},
        ).json()
        store.put(temporary["objectKey"], b"TEMP", content_type="text/markdown")
        response = client.post("/api/v1/library/files/complete-upload", headers=headers,
                               json={"uploadSessionId": temporary["uploadSessionId"],
                                     "lifecycle": "temporary"})
        assert response.status_code == 201
        reserved = client.post(
            "/api/v1/library/files/upload-url", headers=headers,
            json={"fileName": "pending.md", "fileSizeBytes": 9, "mimeType": "text/markdown"},
        ).json()

        with open_database_connection(settings) as connection:
            connection.execute(
                "update library_files set expires_at = '2000-01-01T00:00:00+00:00' where id = ?",
                (temporary["fileId"],),
            )
            connection.commit()
        def space():
            return client.get("/api/v1/library/spaces", headers=headers).json()["items"][0]

        result = space()
        assert result["breakdown"]["permanent"] == {
            "fileCount": 101, "fileBytes": 303, "imageCount": 1, "imageBytes": len(image_bytes)
        }
        assert result["breakdown"]["temporary"] == {
            "fileCount": 1, "fileBytes": 4, "imageCount": 0, "imageBytes": 0
        }
        assert result["usedBytes"] == 307 + len(image_bytes)
        assert result["reservedBytes"] == 9
        assert space() == result
        with open_database_connection(settings) as connection:
            service = LibraryService(connection, store, settings)
            assert service.repo.get_file_by_id(temporary["fileId"]) is not None
            service.purge_expired_temporary_files()
        after_gc = space()
        assert after_gc["usedBytes"] == result["usedBytes"] - 4
        assert after_gc["breakdown"]["temporary"]["fileCount"] == 0
        assert client.delete(
            f"/api/v1/library/files/{files[0]['id']}", headers=headers
        ).status_code == 200
        after_delete = space()
        assert after_delete["breakdown"]["permanent"]["fileCount"] == 100
        assert after_delete["usedBytes"] == after_gc["usedBytes"] - 3
        with open_database_connection(settings) as connection:
            connection.execute(
                "update library_upload_sessions set expires_at = '2000-01-01T00:00:00+00:00' "
                "where id = ?", (reserved["uploadSessionId"],),
            )
            connection.commit()
            service = LibraryService(connection, store, settings)
            assert all(
                row["ledgerUsedBytes"] == row["actualUsedBytes"]
                and row["ledgerReservedBytes"] == row["actualReservedBytes"]
                for row in service.repo.usage_reconciliation_rows("2026-09-10T00:00:00+00:00")
            )
            service.expire_stale_sessions()
        assert space()["reservedBytes"] == 0
