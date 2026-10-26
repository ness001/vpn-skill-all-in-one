"""Offline packaging and helper resolution checks; no agents, profiles or network."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("skill_root", ROOT / "admin/tools/skill_root.py")
skill_root = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(skill_root)
SKILLS = {
    "vpn-client-setup", "vpn-server-setup", "vpn-infra-setup",
    "vpn-diagnose", "vpn-speed",
}


class PackagingTests(unittest.TestCase):
    def test_shared_manifests_and_marketplace(self):
        portable = json.loads((ROOT / "plugin.json").read_text())
        legacy = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(portable.pop("$schema"),
                         "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertEqual(portable, legacy)
        self.assertEqual(legacy["name"], "vpn-skill")
        self.assertEqual(legacy["repository"], "https://github.com/ness001/vpn-skill-all-in-one")
        self.assertEqual(set(legacy), {
            "name", "version", "description", "author", "homepage", "repository",
        })
        market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(market["name"], "vpn-skill")
        self.assertEqual(len(market["plugins"]), 1)
        plugin = market["plugins"][0]
        self.assertEqual(plugin["name"], legacy["name"])
        self.assertEqual((ROOT / plugin["source"]).resolve(), ROOT)
        current = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(current["name"], market["name"])
        self.assertEqual(len(current["plugins"]), 1)
        entry = current["plugins"][0]
        self.assertEqual(entry["name"], plugin["name"])
        self.assertEqual(entry["source"], plugin["source"])
        self.assertEqual(entry["policy"], {
            "installation": "AVAILABLE", "authentication": "ON_INSTALL",
        })
        self.assertEqual(entry["category"], "Productivity")

    def test_one_portable_tree_with_host_neutral_instructions(self):
        paths = list((ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual({path.parent.name for path in paths}, SKILLS)
        self.assertFalse((ROOT / ".claude/skills").exists())
        for path in paths:
            text = path.read_text()
            metadata = text.split("---", 2)[1]
            with self.subTest(skill=path.parent.name):
                self.assertIn(f"name: {path.parent.name}\n", metadata)
                self.assertIn("description:", metadata)
                self.assertNotIn("CLAUDE_", text)
                self.assertNotIn("$ARGUMENTS", text)
                self.assertNotIn("disable-model-invocation", metadata)
                self.assertIn("VPN_SKILL_ROOT", text)
                self.assertIn("skill_root.py", text)
                self.assertIn("working directory", text)
                self.assertIn("Never", text)
                readiness = text.split("## Prepare helpers on first use\n\n", 1)[1].split("Full installation, local-source and update details are at `<root>/docs/INSTALLATION.md`.", 1)[0]
                self.assertIn("git clone --depth 1 https://github.com/ness001/vpn-skill-all-in-one.git", readiness)
                self.assertIn("~/.cache/vpn-skill/source", readiness)
                self.assertIn("lightweight source checkout", readiness)
                self.assertIn("No manual helper installation or environment variable is required", readiness)
                self.assertIn("quoted absolute path", readiness)
                self.assertIn("respect denials", readiness)
                self.assertNotIn("vendor maintenance", readiness)
        sections = [p.read_text().split("## Prepare helpers on first use\n\n", 1)[1].split("Full installation, local-source and update details are at `<root>/docs/INSTALLATION.md`.", 1)[0]
                    for p in paths]
        self.assertTrue(all(section == sections[0] for section in sections))

    def test_simple_installation_has_no_required_checkout_or_environment(self):
        text = (ROOT / "README.md").read_text()
        self.assertNotIn("export VPN_SKILL_ROOT", text)
        self.assertNotIn("git clone", text)
        self.assertNotIn("Server-to-client handoff", text)
        self.assertIn("prepare one shared checkout on first use", text)
        self.assertNotIn("Not published yet", text)
        for agent in ("Claude Code", "Codex", "GitHub Copilot", "Gemini CLI", "npx skills@latest"):
            self.assertIn(agent, text)

    def test_documentation_links(self):
        paths = [ROOT / "README.md", *ROOT.glob("skills/*/SKILL.md")]
        for directory in ("docs", "admin", "examples"):
            paths.extend((ROOT / directory).rglob("*.md"))
        for path in paths:
            text = path.read_text()
            for link in re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", text):
                url = urlsplit(link)
                if url.scheme or url.netloc or not url.path:
                    continue
                destination = (path.parent / unquote(url.path)).resolve()
                with self.subTest(source=path.relative_to(ROOT), link=link):
                    self.assertTrue(destination.is_relative_to(ROOT))
                    self.assertTrue(destination.exists())


class RootResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.base = Path(self.temporary).resolve()
        self.checkout = self.base / "helper checkout with spaces"
        for name in skill_root.REQUIRED:
            path = self.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.skill = self.checkout / "skills/vpn-speed"
        self.skill.mkdir(parents=True)
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.enterContext(patch.object(Path, "cwd", return_value=self.base))
        self.enterContext(patch.object(Path, "home", return_value=self.base / "home"))

    def test_explicit_root_and_environment_ignore_caller_cwd(self):
        self.assertEqual(skill_root.resolve_root(str(self.checkout)), self.checkout)
        with patch.dict(os.environ, {"VPN_SKILL_ROOT": str(self.checkout)}):
            self.assertEqual(skill_root.resolve_root(), self.checkout)
            self.assertEqual(skill_root.resolve_root(skill_dir="/copied/skills/vpn-speed"), self.checkout)
        with patch.dict(os.environ, {"VPN_SKILL_ROOT": "/missing"}):
            self.assertEqual(skill_root.resolve_root(str(self.checkout)), self.checkout)
            with self.assertRaises(ValueError):
                skill_root.resolve_root(skill_dir=str(self.skill))

    def test_full_plugin_path_and_copied_skill_path(self):
        self.assertEqual(skill_root.resolve_root(skill_dir=str(self.skill)), self.checkout)
        copied = self.base / "agent/skills/vpn-speed"
        copied.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "No complete helper checkout"):
            skill_root.resolve_root(skill_dir=str(copied))
        with self.assertRaises(ValueError):
            skill_root.resolve_root()
        with self.assertRaises(ValueError):
            skill_root.resolve_root("relative")

    def test_missing_asset_fails_without_opening_any_asset(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("No content reads")):
            self.assertEqual(skill_root.resolve_root(str(self.checkout)), self.checkout)
            (self.checkout / "clients/vpn.py").unlink()
            with self.assertRaisesRegex(ValueError, "Incomplete helper checkout"):
                skill_root.resolve_root(str(self.checkout))

    def test_cli_resolves_from_unrelated_working_directory(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "admin/tools/skill_root.py"), "--root", str(self.checkout)],
            cwd=self.base, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.checkout))

    def test_cached_root_is_available_to_copied_skills(self):
        cached = skill_root.cache_root()
        for name in skill_root.REQUIRED:
            path = cached / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        copied = self.base / "agent with spaces/skills/vpn-speed"
        self.assertEqual(skill_root.resolve_root(skill_dir=str(copied)), cached)
        self.assertEqual(skill_root.resolve_root(), cached)
        self.assertEqual(skill_root.resolve_root(skill_dir=str(self.skill)), self.checkout)
        self.assertEqual(skill_root.resolve_root(str(self.checkout)), self.checkout)

    def test_nearby_root_and_toolkit_child_are_checked_not_assumed(self):
        project = self.checkout / "work/subdirectory"
        self.assertEqual(skill_root.resolve_root(cwd=project), self.checkout)
        parent = self.base / "private parent"
        (parent / "toolkit").parent.mkdir(parents=True)
        (parent / "toolkit").symlink_to(self.checkout, target_is_directory=True)
        self.assertEqual(skill_root.resolve_root(cwd=parent / "clients"), self.checkout)
        with self.assertRaises(ValueError):
            skill_root.resolve_root(cwd=self.base / "unrelated")

    def test_editable_source_rejects_plugin_and_uses_cached_git_source(self):
        cached = skill_root.cache_root()
        for name in skill_root.REQUIRED:
            path = cached / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (cached / ".git").mkdir()
        self.assertEqual(skill_root.resolve_root(skill_dir=str(self.skill), editable=True), cached)
        with self.assertRaisesRegex(ValueError, "editable Git"):
            skill_root.resolve_root(str(self.checkout), editable=True)
        (self.checkout / ".git").write_text("gitdir: synthetic")
        self.assertEqual(skill_root.resolve_root(str(self.checkout), editable=True), self.checkout)

    def test_missing_helpers_report_preparation_without_downloading(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("No downloads")):
            with self.assertRaisesRegex(ValueError, "first-use instructions"):
                skill_root.resolve_root(cwd=self.base / "unrelated")

    def test_default_runtime_storage_is_not_in_source(self):
        sys.path.insert(0, str(ROOT / "clients"))
        self.addCleanup(sys.path.remove, str(ROOT / "clients"))
        import vpn_common
        self.assertFalse(vpn_common.TOOLS.is_relative_to(ROOT))
        sys.path.insert(0, str(ROOT / "admin/tools"))
        self.addCleanup(sys.path.remove, str(ROOT / "admin/tools"))
        import speed_common
        expected = self.base / "home/.cache/vpn-skill/runtime/.local/speed-tests/new.json"
        self.assertEqual(speed_common.output_path(Path(".local/speed-tests/new.json")), expected)

    def test_source_checkout_has_all_helpers(self):
        self.assertEqual(skill_root.resolve_root(str(ROOT)), ROOT)
        self.assertEqual(skill_root.resolve_root(skill_dir=str(ROOT / "skills/vpn-speed")), ROOT)


if __name__ == "__main__":
    unittest.main()
