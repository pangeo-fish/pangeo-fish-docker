"""Resolve source versions and publish aliases for already tested GHCR images."""

import json
import os
import re
import subprocess
import sys
import urllib.request


def git_sha(repo, ref):
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    result = subprocess.run(
        [
            "git",
            "ls-remote",
            repo,
            f"refs/heads/{ref}",
            f"refs/tags/{ref}",
            f"refs/tags/{ref}^{{}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    refs = dict(line.split()[::-1] for line in result.stdout.splitlines())
    sha = (
        refs.get(f"refs/tags/{ref}^{{}}")
        or refs.get(f"refs/heads/{ref}")
        or refs.get(f"refs/tags/{ref}")
    )
    if not sha or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"Cannot resolve pangeo-fish ref: {ref}")
    return sha


def resolve(env):
    notebook_tag = env.get("INPUT_NOTEBOOK_TAG", "")
    if not notebook_tag:
        url = (
            "https://hub.docker.com/v2/repositories/pangeo/pangeo-notebook/"
            "tags?page_size=100&ordering=last_updated"
        )
        with urllib.request.urlopen(url, timeout=60) as response:
            tags = json.load(response)["results"]
        dated = [
            tag["name"]
            for tag in tags
            if re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}", tag["name"])
        ]
        if not dated:
            raise ValueError("No dated Pangeo Notebook release found")
        notebook_tag = max(dated)
    release_tag = env.get("PAYLOAD_RELEASE_TAG", "")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", notebook_tag):
        raise ValueError("Invalid Pangeo Notebook image tag")
    if release_tag:
        if release_tag == "latest" or not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", release_tag
        ):
            raise ValueError("Release tag must be a Docker tag other than latest")
        if not env.get("PAYLOAD_SHA"):
            raise ValueError("Release notifications must include their source commit")
    payload_sha = env.get("PAYLOAD_SHA", "")
    if payload_sha and not re.fullmatch(r"[0-9a-f]{40}", payload_sha):
        raise ValueError("Dispatch sha must be a full commit SHA")
    fish_ref = env.get("INPUT_FISH_REF") or payload_sha or "main"
    fish_sha = git_sha(env["PANGEO_FISH_REPO"], fish_ref)
    is_default = not (
        env.get("INPUT_NOTEBOOK_TAG") or env.get("INPUT_FISH_REF") or release_tag
    )
    return {
        "notebook_tag": notebook_tag,
        "fish_sha": fish_sha,
        "image_tag": f"{notebook_tag}-{fish_sha[:7]}",
        "is_default": str(is_default).lower(),
        "release_tag": release_tag,
    }


def manifest_digest(ref, optional=False):
    result = subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            ref,
            "--format",
            "{{json .Manifest}}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if optional and any(
            message in result.stderr.lower()
            for message in ("not found", "manifest unknown")
        ):
            return None
        raise RuntimeError(f"Cannot inspect {ref}: {result.stderr.strip()}")
    digest = json.loads(result.stdout)["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"Invalid manifest digest for {ref}")
    return digest


def publish(env):
    image = env["IMAGE"]
    source = f"{image}:{env['IMAGE_TAG']}"
    digest = manifest_digest(source)
    aliases = []
    release_tag = env.get("RELEASE_TAG", "")
    if release_tag:
        aliases.append(release_tag)
    if env.get("IS_DEFAULT") == "true":
        # Delayed notifications must not move latest back to an older commit.
        if git_sha(env["PANGEO_FISH_REPO"], "main") == env["FISH_SHA"]:
            aliases.append("latest")
        else:
            print("Skipping latest: main has advanced beyond this build")
    changed = False
    for alias in aliases:
        target = f"{image}:{alias}"
        existing = manifest_digest(target, optional=True)
        if alias == release_tag and existing and existing != digest:
            raise ValueError(f"Refusing to overwrite existing release image {target}")
        if existing != digest:
            subprocess.run(
                [
                    "docker",
                    "buildx",
                    "imagetools",
                    "create",
                    "--prefer-index=false",
                    "--tag",
                    target,
                    f"{image}@{digest}",
                ],
                check=True,
            )
            changed = True
        with open(env["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(f"- `{target}` → `{digest}`\n")
    return {"aliases": json.dumps(aliases), "changed": str(changed).lower()}


def main():
    outputs = {"resolve": resolve, "publish": publish}[sys.argv[1]](os.environ)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in outputs.items():
            output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
