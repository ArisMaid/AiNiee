import json
import os
import subprocess
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from UserInterface.VersionManager.VersionManager import VersionManager


class VersionManagerPortableUpdateTests(unittest.TestCase):
    def setUp(self):
        self.manager = VersionManager(version="AiNiee 7.2.4 dev")

    @patch.dict(os.environ, {'AINIEE_RPG_APP':'1'})
    def test_rpg_update_skips_source_zip_and_uses_fork(self):
        from ModuleFolders.Infrastructure.Platform.PlatformPaths import release_api_url
        self.assertIn('ArisMaid/AiNiee',release_api_url())
        assets=[{'name':'AiNieeRPG-source-7.2.4.1.zip','browser_download_url':'source'},
            {'name':'AiNieeRPG-7.2.4.1-windows-x64.zip','browser_download_url':'application'}]
        self.assertEqual(self.manager._find_download_url(assets),'application')
        self.assertIsNone(self.manager._find_download_url(assets[:1]))

    @patch("UserInterface.VersionManager.VersionManager.is_macos", return_value=False)
    def test_non_macos_updates_always_use_zip(self, _mock_is_macos):
        self.assertEqual(self.manager._update_file_suffix(), ".zip")
        self.assertEqual(self.manager._expected_update_asset_suffix(), ".zip")

    @patch("UserInterface.VersionManager.VersionManager.is_macos", return_value=False)
    def test_executable_is_not_a_download_candidate(self, _mock_is_macos):
        executable_asset = {
            "name": "AiNiee-7.3.0-Legacy-Package.exe",
            "browser_download_url": "https://example.invalid/AiNiee-7.3.0-Legacy-Package.exe",
        }
        portable_asset = {
            "name": "AiNiee-7.3.0-Windows-Portable.zip",
            "browser_download_url": "https://example.invalid/AiNiee-7.3.0-Windows-Portable.zip",
        }

        self.assertIsNone(self.manager._find_download_url([executable_asset]))
        self.assertEqual(
            self.manager._find_download_url([executable_asset, portable_asset]),
            portable_asset["browser_download_url"],
        )

    @patch("UserInterface.VersionManager.VersionManager.is_macos", return_value=False)
    def test_release_selection_chooses_newest_stable_portable_zip(self, _mock_is_macos):
        releases = [
            {
                "tag_name": "v9.0.0",
                "draft": False,
                "prerelease": True,
                "assets": [
                    {
                        "name": "AiNiee-9.0.0-Windows-Portable.zip",
                        "browser_download_url": "https://example.invalid/9.0.0.zip",
                    }
                ],
            },
            {
                "tag_name": "v8.0.0",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": "AiNiee-8.0.0-Legacy-Package.exe",
                        "browser_download_url": "https://example.invalid/8.0.0.exe",
                    }
                ],
            },
            {
                "tag_name": "v7.4.0",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": "AiNiee-7.4.0-Windows-Portable.zip",
                        "browser_download_url": "https://example.invalid/7.4.0.zip",
                    }
                ],
            },
            {
                "tag_name": "v7.3.0",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": "AiNiee-7.3.0-Windows-Portable.zip",
                        "browser_download_url": "https://example.invalid/7.3.0.zip",
                    }
                ],
            },
        ]

        release, version, download_url = self.manager._select_compatible_update_release(releases)

        self.assertEqual(release["tag_name"], "v7.4.0")
        self.assertEqual(version, "7.4.0")
        self.assertEqual(download_url, "https://example.invalid/7.4.0.zip")

    @patch("UserInterface.VersionManager.VersionManager.is_windows", return_value=False)
    @patch("UserInterface.VersionManager.VersionManager.is_macos", return_value=False)
    def test_portable_zip_starts_bundled_updater(self, _mock_is_macos, _mock_is_windows):
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            updater_path = temp_root / "updater.exe"
            update_path = temp_root / "AiNiee-update.zip"
            info_path = temp_root / "download_info.json"
            updater_path.touch()
            update_path.touch()
            info_path.touch()

            with (
                patch(
                    "UserInterface.VersionManager.VersionManager.resource_path",
                    return_value=updater_path,
                ),
                patch.object(
                    self.manager,
                    "_download_paths",
                    return_value=(update_path, temp_root / "unused.temp", info_path),
                ),
                patch.object(self.manager, "_exit_for_update") as exit_for_update,
                patch("subprocess.Popen") as popen,
            ):
                self.manager._run_updater(str(update_path))

            popen.assert_called_once()
            command = popen.call_args.args[0]
            self.assertEqual(command[0], str(updater_path))
            self.assertEqual(command[1], str(update_path))
            self.assertTrue(command[1].endswith(".zip"))
            self.assertFalse(info_path.exists())
            exit_for_update.assert_called_once_with()

    @patch("UserInterface.VersionManager.VersionManager.is_macos", return_value=False)
    def test_portable_zip_download_resumes_and_finishes(self, _mock_is_macos):
        with TemporaryDirectory() as temp_dir:
            download_root = Path(temp_dir)
            local_path = download_root / "AiNiee-update.zip"
            temp_path = download_root / "AiNiee-update.zip.temp"
            info_path = download_root / "download_info.json"
            url = "https://example.invalid/AiNiee-7.4.0-Windows-Portable.zip"
            temp_path.write_bytes(b"abc")
            info_path.write_text(
                json.dumps(
                    {
                        "url": url,
                        "version": "7.4.0",
                        "total_size": 6,
                        "downloaded": 3,
                        "status": "paused",
                    }
                ),
                encoding="utf-8",
            )

            head_response = MagicMock()
            head_response.headers = {"content-length": "6"}
            download_response = MagicMock()
            download_response.__enter__.return_value = download_response
            download_response.__exit__.return_value = False
            download_response.status_code = 206
            download_response.headers = {"content-length": "3"}
            download_response.iter_content.return_value = [b"def"]

            completed = []
            self.manager.latest_version = "7.4.0"
            self.manager.signals.download_completed.disconnect()
            self.manager.signals.download_failed.disconnect()
            self.manager.signals.progress_updated.disconnect()
            self.manager.signals.download_completed.connect(completed.append)

            with (
                patch(
                    "UserInterface.VersionManager.VersionManager.downloads_dir",
                    return_value=download_root,
                ),
                patch(
                    "UserInterface.VersionManager.VersionManager.requests.head",
                    return_value=head_response,
                ),
                patch(
                    "UserInterface.VersionManager.VersionManager.requests.get",
                    return_value=download_response,
                ) as get_request,
            ):
                self.manager._download_update(url)

            self.assertEqual(get_request.call_args.kwargs["headers"], {"Range": "bytes=3-"})
            self.assertEqual(local_path.read_bytes(), b"abcdef")
            self.assertFalse(temp_path.exists())
            self.assertEqual(json.loads(info_path.read_text(encoding="utf-8"))["status"], "completed")
            self.assertEqual(completed, [str(local_path)])

    @unittest.skipUnless(
        os.name == "nt" and os.environ.get("AINIEE_RUN_UPDATER_SMOKE") == "1",
        "set AINIEE_RUN_UPDATER_SMOKE=1 on Windows to run the bundled updater smoke test",
    )
    def test_bundled_updater_overlays_portable_package(self):
        repository_root = Path(__file__).resolve().parents[1]
        updater_path = repository_root / "Resource" / "Updater" / "updater.exe"
        self.assertTrue(updater_path.exists())

        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target_dir = temp_root / "target"
            target_dir.mkdir()
            (target_dir / "AiNiee.exe").write_text("old-binary", encoding="utf-8")

            update_path = temp_root / "update.zip"
            with zipfile.ZipFile(update_path, "w") as archive:
                archive.writestr("package/AiNiee.exe", "new-binary")
                archive.writestr("package/payload.txt", "updated-payload")

            result = subprocess.run(
                [str(updater_path), str(update_path), str(target_dir)],
                cwd=repository_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((target_dir / "AiNiee.exe").read_text(encoding="utf-8"), "new-binary")
            self.assertEqual((target_dir / "payload.txt").read_text(encoding="utf-8"), "updated-payload")
            self.assertFalse(update_path.exists())


if __name__ == "__main__":
    unittest.main()
