"""
Audit fix regression tests for the gateway modules.

Covers:
  - M2: GatewayParserWrapper validates the parser with os.X_OK (execute bit),
        not just os.R_OK. A readable-but-non-executable parser must be rejected;
        an executable one must pass validation.
"""

import os
import tempfile
import unittest

from core.gateway_parser_wrapper import GatewayParserWrapper


class TestParserExecutableValidation(unittest.TestCase):
    """M2: parser must be validated for the execute bit, not just readability."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="gw_test_")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_parser(self, mode: int) -> str:
        """Create a tiny shebang script with the given chmod mode."""
        path = os.path.join(self.tmpdir, "GWMReader.py")
        with open(path, "w") as f:
            f.write("#!/usr/bin/env python3\nprint('hi')\n")
        os.chmod(path, mode)
        return path

    def _wrapper(self, parser_path: str) -> GatewayParserWrapper:
        # A real input file so input validation isn't what trips first.
        input_file = os.path.join(self.tmpdir, "input.bin")
        with open(input_file, "wb") as f:
            f.write(b"\x00")
        return GatewayParserWrapper(
            site_name="TestSite",
            file_paths=[input_file],
            parser_exe_path=parser_path,
            temp_base_dir=self.tmpdir,
        )

    def test_readable_non_executable_parser_is_rejected(self):
        # 0o644 = rw-r--r-- : readable but NOT executable.
        parser_path = self._make_parser(0o644)
        # Sanity: it is readable but not executable.
        self.assertTrue(os.access(parser_path, os.R_OK))
        self.assertFalse(os.access(parser_path, os.X_OK))

        wrapper = self._wrapper(parser_path)
        with self.assertRaises(PermissionError):
            wrapper._validate_parser_executable()

    def test_executable_parser_passes_validation(self):
        # 0o755 = rwxr-xr-x : readable and executable.
        parser_path = self._make_parser(0o755)
        self.assertTrue(os.access(parser_path, os.X_OK))

        wrapper = self._wrapper(parser_path)
        # Should not raise.
        wrapper._validate_parser_executable()

    def test_missing_parser_path_raises_value_error(self):
        wrapper = self._wrapper("")
        wrapper.parser_exe_path = None
        with self.assertRaises(ValueError):
            wrapper._validate_parser_executable()

    def test_nonexistent_parser_raises_file_not_found(self):
        wrapper = self._wrapper(os.path.join(self.tmpdir, "does_not_exist"))
        with self.assertRaises(FileNotFoundError):
            wrapper._validate_parser_executable()


if __name__ == "__main__":
    unittest.main()
