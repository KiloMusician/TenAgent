"""Start-up behaviour of dashboard/serve.py: which address it prints, opens and probes."""

import contextlib
import io
import os
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from http_harness import DashboardCase, MODULE_ROOT  # noqa: E402


def ipv6_loopback_available():
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6) as probe:
            probe.bind(("::1", 0))
        return True
    except OSError:
        return False


class FakeServer:
    server_address = ("127.0.0.1", 7777)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def serve_forever(self):
        raise KeyboardInterrupt


class LaunchTests(DashboardCase):
    def run_main(self, port=7777, env_password=None):
        serve = self.serve
        opened = []
        out = io.StringIO()
        patches = {
            "start_workspace_watcher": lambda root: None,
            "cli_status_background_worker": lambda root: None,
            "local_providers_probe_worker": lambda root: None,
            "start_server_with_auto_port": lambda *a, **k: (FakeServer(), port),
        }
        saved = {name: getattr(serve, name) for name in patches}
        for name, value in patches.items():
            setattr(serve, name, value)
        real_open = serve.webbrowser.open
        serve.webbrowser.open = lambda url, *a, **k: opened.append(url)
        cwd = os.getcwd()
        try:
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit):
                    serve.main()
        finally:
            os.chdir(cwd)
            serve.webbrowser.open = real_open
            for name, value in saved.items():
                setattr(serve, name, value)
        return opened, out.getvalue()

    def test_printed_and_opened_urls_use_the_address_the_server_binds(self):
        opened, output = self.run_main(port=7791)
        self.assertEqual(opened, ["http://127.0.0.1:7791/dashboard/"])
        self.assertIn("http://127.0.0.1:7791/dashboard/", output)
        self.assertNotIn("localhost", output)

    def test_short_operator_passwords_are_warned_about_but_accepted(self):
        for password, warned in (("short-pw", True), ("exactly-12-ch", False), ("x" * 11, True),
                                 ("y" * 12, False)):
            with self.subTest(password=len(password)):
                self.serve._DASHBOARD_PASSWORD = password
                os.environ["TENAGENT_DASHBOARD_PASSWORD"] = password
                self.addCleanup(os.environ.pop, "TENAGENT_DASHBOARD_PASSWORD", None)
                opened, output = self.run_main()
                self.assertEqual(opened, ["http://127.0.0.1:7777/dashboard/"], "must still start")
                self.assertEqual("WARNING" in output and "12" in output, warned, output)

    def test_generated_passwords_do_not_trigger_the_warning(self):
        os.environ.pop("TENAGENT_DASHBOARD_PASSWORD", None)
        self.serve._DASHBOARD_PASSWORD = "g" * 32
        _, output = self.run_main()
        self.assertNotIn("WARNING", output)

    def test_readme_points_at_the_bound_address(self):
        readme = (MODULE_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("localhost:7777", readme)
        self.assertIn("http://127.0.0.1:7777/dashboard/", readme)

    @unittest.skipUnless(ipv6_loopback_available(), "IPv6 loopback not available")
    def test_a_port_held_on_ipv6_loopback_is_not_used(self):
        holder = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.addCleanup(holder.close)
        holder.bind(("::1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        self.assertFalse(self.serve.is_port_available(port))

    def test_free_ports_are_still_available(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.assertTrue(self.serve.is_port_available(port))

    def test_auto_port_skips_a_port_held_on_ipv6_loopback(self):
        if not ipv6_loopback_available():
            self.skipTest("IPv6 loopback not available")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            start = probe.getsockname()[1]
        holder = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.addCleanup(holder.close)
        try:
            holder.bind(("::1", start))
        except OSError:
            self.skipTest("could not claim the chosen port on ::1")
        holder.listen(1)
        httpd, port = self.serve.start_server_with_auto_port(start, 20)
        self.addCleanup(httpd.server_close)
        self.assertNotEqual(port, start)


if __name__ == "__main__":
    unittest.main()
