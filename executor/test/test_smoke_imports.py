import unittest


class TestSmokeImports(unittest.TestCase):
    def test_import_executor(self):
        import executor  # noqa: F401
