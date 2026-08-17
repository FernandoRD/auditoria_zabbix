import unittest
from unittest import mock

from core import pandoc_runtime


class PandocRuntimeTests(unittest.TestCase):
    def test_two_component_modern_version_is_accepted(self):
        self.assertEqual((3, 10, 0), pandoc_runtime._version_tuple("3.10"))

    def test_source_missing_pandoc_requires_consent_without_downloading(self):
        fake_pandoc = mock.Mock()
        fake_pandoc.get_pandoc_version.side_effect = OSError("ausente")

        with mock.patch.object(pandoc_runtime, "is_frozen_app", return_value=False), mock.patch.object(
            pandoc_runtime, "_prepare_pypandoc", return_value=fake_pandoc
        ):
            with self.assertRaises(pandoc_runtime.PandocDownloadRequired):
                pandoc_runtime.load_pandoc(allow_download=False)

        fake_pandoc.download_pandoc.assert_not_called()

    def test_source_download_happens_only_after_consent(self):
        fake_pandoc = mock.Mock()
        fake_pandoc.get_pandoc_version.side_effect = [
            OSError("ausente"),
            OSError("ainda ausente"),
            "3.1.7",
        ]

        with mock.patch.object(pandoc_runtime, "is_frozen_app", return_value=False), mock.patch.object(
            pandoc_runtime, "_prepare_pypandoc", return_value=fake_pandoc
        ), mock.patch.object(pandoc_runtime, "_download_source_pandoc") as download:
            result = pandoc_runtime.load_pandoc(allow_download=True)

        self.assertIs(result, fake_pandoc)
        download.assert_called_once()

    def test_frozen_app_never_downloads_when_bundled_pandoc_is_invalid(self):
        fake_pandoc = mock.Mock()
        fake_pandoc.get_pandoc_version.side_effect = OSError("inválido")

        with mock.patch.object(pandoc_runtime, "is_frozen_app", return_value=True), mock.patch.object(
            pandoc_runtime, "_prepare_pypandoc", return_value=fake_pandoc
        ):
            with self.assertRaisesRegex(
                pandoc_runtime.PandocUnavailableError, "Nenhum download foi tentado"
            ):
                pandoc_runtime.load_pandoc(allow_download=True)

        fake_pandoc.download_pandoc.assert_not_called()

    def test_frozen_app_accepts_minimum_bundled_version(self):
        fake_pandoc = mock.Mock()
        fake_pandoc.get_pandoc_version.return_value = "3.1.7"

        with mock.patch.object(pandoc_runtime, "is_frozen_app", return_value=True), mock.patch.object(
            pandoc_runtime, "_prepare_pypandoc", return_value=fake_pandoc
        ):
            result = pandoc_runtime.load_pandoc()

        self.assertIs(result, fake_pandoc)
        fake_pandoc.download_pandoc.assert_not_called()

    def test_download_requirement_reports_old_source_version(self):
        fake_pandoc = mock.Mock()
        fake_pandoc.get_pandoc_version.return_value = "3.1.6"

        with mock.patch.object(pandoc_runtime, "is_frozen_app", return_value=False), mock.patch.object(
            pandoc_runtime, "_prepare_pypandoc", return_value=fake_pandoc
        ):
            requirement = pandoc_runtime.pandoc_download_requirement()

        self.assertIn("3.1.6", requirement)
        self.assertIn("3.1.7", requirement)


if __name__ == "__main__":
    unittest.main()
