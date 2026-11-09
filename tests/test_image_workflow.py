import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "image_workflow", Path(__file__).parents[1] / "scripts/image_workflow.py"
)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)
SHA = "a" * 40
OTHER_SHA = "b" * 40
DIGEST = "sha256:" + "c" * 64
OTHER_DIGEST = "sha256:" + "d" * 64
IMAGE = "ghcr.io/pangeo-fish/pangeo-fish-notebook"


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "PANGEO_FISH_REPO": "https://github.com/pangeo-fish/pangeo-fish.git",
            "INPUT_NOTEBOOK_TAG": "2026.10.21",
            "PAYLOAD_SHA": SHA,
        }

    def test_main_notification_uses_exact_sha(self):
        self.env.pop("INPUT_NOTEBOOK_TAG")
        response = io.StringIO(
            json.dumps(
                {
                    "results": [
                        {"name": "master"},
                        {"name": "2026.06.04"},
                        {"name": "2026.10.21"},
                        {"name": "2026.10.21-abcdef0"},
                    ]
                }
            )
        )
        with patch.object(workflow.urllib.request, "urlopen", return_value=response):
            result = workflow.resolve(self.env)
        self.assertEqual(result["fish_sha"], SHA)
        self.assertEqual(result["image_tag"], "2026.10.21-aaaaaaa")
        self.assertEqual(result["is_default"], "true")

    def test_release_notification_never_updates_latest(self):
        self.env["PAYLOAD_RELEASE_TAG"] = "v1.2.3-rc.1"
        result = workflow.resolve(self.env)
        self.assertEqual(result["release_tag"], "v1.2.3-rc.1")
        self.assertEqual(result["fish_sha"], SHA)
        self.assertEqual(result["is_default"], "false")

    def test_manual_pin_does_not_update_latest(self):
        self.env["INPUT_FISH_REF"] = OTHER_SHA
        result = workflow.resolve(self.env)
        self.assertEqual(result["fish_sha"], OTHER_SHA)
        self.assertEqual(result["is_default"], "false")

    def test_annotated_tag_resolves_to_commit_not_tag_object(self):
        stdout = f"{OTHER_SHA}\trefs/tags/v1.2.3\n{SHA}\trefs/tags/v1.2.3^{{}}\n"
        with patch.object(
            workflow.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, stdout, ""),
        ):
            self.assertEqual(workflow.git_sha("repo", "v1.2.3"), SHA)

    def test_missing_ref_fails_before_build(self):
        with patch.object(
            workflow.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ):
            with self.assertRaisesRegex(ValueError, "Cannot resolve"):
                workflow.git_sha("repo", "missing")

    def test_rejects_invalid_release_tags_and_output_injection(self):
        for tag in ("latest", "release/v1", "v1\nfish_sha=other", "x" * 129):
            with self.subTest(tag=tag):
                self.env["PAYLOAD_RELEASE_TAG"] = tag
                with self.assertRaises(ValueError):
                    workflow.resolve(self.env)

    def test_release_requires_full_source_sha(self):
        self.env["PAYLOAD_RELEASE_TAG"] = "v1.2.3"
        for sha in ("", "main", SHA[:7]):
            with self.subTest(sha=sha):
                self.env["PAYLOAD_SHA"] = sha
                with self.assertRaises(ValueError):
                    workflow.resolve(self.env)

    def test_scheduled_build_resolves_main(self):
        self.env.pop("PAYLOAD_SHA")
        self.env.pop("INPUT_NOTEBOOK_TAG")
        with patch.object(workflow, "git_sha", return_value=SHA) as resolve_sha:
            with patch.object(
                workflow.urllib.request,
                "urlopen",
                return_value=io.StringIO('{"results":[{"name":"2026.10.21"}]}'),
            ):
                result = workflow.resolve(self.env)
        resolve_sha.assert_called_once_with(self.env["PANGEO_FISH_REPO"], "main")
        self.assertEqual(result["is_default"], "true")


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = {
            "IMAGE": IMAGE,
            "IMAGE_TAG": "2026.10.21-aaaaaaa",
            "FISH_SHA": SHA,
            "PANGEO_FISH_REPO": "repo",
            "GITHUB_STEP_SUMMARY": str(Path(self.temp.name) / "summary"),
            "IS_DEFAULT": "false",
            "RELEASE_TAG": "",
        }

    def test_existing_commit_image_can_receive_release_alias(self):
        self.env["RELEASE_TAG"] = "v1.2.3"
        with patch.object(workflow, "manifest_digest", side_effect=[DIGEST, None]):
            with patch.object(workflow.subprocess, "run") as run:
                result = workflow.publish(self.env)
        run.assert_called_once_with(
            [
                "docker",
                "buildx",
                "imagetools",
                "create",
                "--prefer-index=false",
                "--tag",
                IMAGE + ":v1.2.3",
                IMAGE + "@" + DIGEST,
            ],
            check=True,
        )
        self.assertEqual(json.loads(result["aliases"]), ["v1.2.3"])
        self.assertEqual(result["changed"], "true")

    def test_release_rerun_is_idempotent(self):
        self.env["RELEASE_TAG"] = "v1.2.3"
        with patch.object(workflow, "manifest_digest", return_value=DIGEST):
            with patch.object(workflow.subprocess, "run") as run:
                result = workflow.publish(self.env)
        run.assert_not_called()
        self.assertEqual(result["changed"], "false")

    def test_release_cannot_overwrite_another_image(self):
        self.env["RELEASE_TAG"] = "v1.2.3"
        with patch.object(
            workflow, "manifest_digest", side_effect=[DIGEST, OTHER_DIGEST]
        ):
            with patch.object(workflow.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                    workflow.publish(self.env)
        run.assert_not_called()

    def test_latest_moves_to_current_main(self):
        self.env["IS_DEFAULT"] = "true"
        with patch.object(workflow, "git_sha", return_value=SHA):
            with patch.object(
                workflow, "manifest_digest", side_effect=[DIGEST, OTHER_DIGEST]
            ):
                with patch.object(workflow.subprocess, "run") as run:
                    result = workflow.publish(self.env)
        self.assertEqual(json.loads(result["aliases"]), ["latest"])
        self.assertEqual(
            run.call_args.args[0][-2:], [IMAGE + ":latest", IMAGE + "@" + DIGEST]
        )

    def test_delayed_main_notification_does_not_roll_back_latest(self):
        self.env["IS_DEFAULT"] = "true"
        with patch.object(workflow, "git_sha", return_value=OTHER_SHA):
            with patch.object(workflow, "manifest_digest", return_value=DIGEST):
                with patch.object(workflow.subprocess, "run") as run:
                    result = workflow.publish(self.env)
        run.assert_not_called()
        self.assertEqual(json.loads(result["aliases"]), [])

    def test_manual_pin_has_no_aliases(self):
        with patch.object(workflow, "manifest_digest", return_value=DIGEST):
            with patch.object(workflow.subprocess, "run") as run:
                result = workflow.publish(self.env)
        run.assert_not_called()
        self.assertEqual(json.loads(result["aliases"]), [])

    def test_registry_errors_are_not_treated_as_missing_tags(self):
        with patch.object(
            workflow.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, "", "unauthorized"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unauthorized"):
                workflow.manifest_digest(IMAGE + ":v1.2.3", optional=True)

    def test_missing_manifest_can_be_created(self):
        with patch.object(
            workflow.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, "", "manifest unknown"),
        ):
            self.assertIsNone(
                workflow.manifest_digest(IMAGE + ":v1.2.3", optional=True)
            )


if __name__ == "__main__":
    unittest.main()
