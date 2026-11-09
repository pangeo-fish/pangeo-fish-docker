# pangeo-fish-docker

Docker image = [`pangeo/pangeo-notebook`](https://github.com/pangeo-data/pangeo-docker-images)
+ a dedicated conda environment `pangeo-fish` (Python 3.11) with
[pangeo-fish](https://github.com/pangeo-fish/pangeo-fish) installed, exposed in
JupyterLab as the kernel **"Python (pangeo-fish)"**.

```
ghcr.io/pangeo-fish/pangeo-fish-notebook:latest
ghcr.io/pangeo-fish/pangeo-fish-notebook:<pangeo-notebook tag>-<pangeo-fish short sha>
ghcr.io/pangeo-fish/pangeo-fish-notebook:<pangeo-fish release tag>
```

## Use it on pangeo-eosc

In the JupyterHub server options, choose a custom image and enter

```
ghcr.io/pangeo-fish/pangeo-fish-notebook:latest
```

(or a fixed `<date>-<sha>` tag for reproducibility). Then pick the kernel
"Python (pangeo-fish)" in your notebook. In a terminal:

```bash
conda activate pangeo-fish
```

## What the image contains

See [`Dockerfile`](Dockerfile). It does the equivalent of

```bash
git clone https://github.com/pangeo-fish/pangeo-fish.git /srv/pangeo-fish
conda create -n pangeo-fish python=3.11 pip git eccodes ipykernel ipywidgets
conda activate pangeo-fish
pip install /srv/pangeo-fish        # torch, if needed, from the CPU-only index
python -m ipykernel install --prefix /srv/conda/envs/notebook \
    --name pangeo-fish --display-name "Python (pangeo-fish)"
```

The source lives in `/srv/pangeo-fish` (not `$HOME`) and the kernel is
registered in the notebook environment (not `--user`), because on JupyterHub
the home directory is a persistent volume mounted over the image's `$HOME`.

## When is the image rebuilt?

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs:

| Trigger | Behaviour |
|---|---|
| daily schedule | builds only if there is a new pangeo-notebook release **or** a new commit on pangeo-fish `main` (i.e. the tag `<notebook>-<sha>` does not exist yet) |
| `repository_dispatch` (`pangeo-fish-updated`) | immediately builds the supplied source commit if missing; a release notification also publishes its release tag |
| push to `main` of this repo | always rebuilds and pushes |
| pull request | builds and tests, does not push |
| manual (`workflow_dispatch`) | optional `force`, pangeo-notebook tag and pangeo-fish ref |

Each build runs a smoke test (`import pangeo_fish`, kernel registered) before pushing.

`latest` tracks the current source `main` and is updated only by default-version
builds. A delayed notification for an older commit cannot move it backwards.
Manually pinned builds and release notifications do not update `latest`.

Release notifications publish the exact release tag, including prerelease tags
such as `v1.2.3-rc.1`. Release aliases are added even when the commit's tested
image already exists, without downloading or rebuilding it. An existing release
alias is never overwritten with a different digest. Distinct release
notifications have separate concurrency groups so that pending releases are not
replaced by a subsequent `main` notification.

## Connect source events (one-time setup)

Merge this repository's release-tag support before enabling the source workflow.
Install [`extras/notify-docker-image.yml`](extras/notify-docker-image.yml) as
`.github/workflows/notify-docker-image.yml` in `pangeo-fish/pangeo-fish`.
It requests images on pushes to `main` and on GitHub Release publication
(`release: published`, including prereleases).

In the **source repository**, configure the Actions secret
`DOCKER_IMAGE_DISPATCH_TOKEN`: a fine-grained personal access token (or GitHub App
token) limited to `pangeo-fish/pangeo-fish-docker` with **Contents: Read and write**.
The source repository's default `GITHUB_TOKEN` cannot dispatch to another
repository. Renew the token before expiry. The Docker repository's own
`GITHUB_TOKEN` is used for GHCR publication; no registry token is sent by the
source workflow.

The dispatch payload is:

```json
{
  "event_type": "pangeo-fish-updated",
  "client_payload": {
    "sha": "<full 40-character source commit SHA>",
    "release_tag": "v1.2.3"
  }
}
```

For a `main` push, omit `release_tag` or set it to an empty string. Release tags
must be valid Docker tags (at most 128 ASCII letters, digits, underscores,
periods, or hyphens; first character must be a letter, digit, or underscore).
`latest` is reserved for `main`. Annotated source tags are resolved to their
underlying commit when used as a manual `pangeo_fish_ref`.

The source workflow confirms request acceptance. Check this repository's
**Build and publish image** run for the actual build and publication result.
Rerun a failed source notification after fixing its secret; rerun a failed
Docker workflow here. The daily fallback still checks `main` and base-image
updates, but does not recover missed release notifications.

Workflow logic can be checked without Docker or network access:

```bash
python3 -m unittest discover -s tests -v
```

## Build locally

```bash
docker build -t pangeo-fish-notebook \
  --build-arg PANGEO_NOTEBOOK_TAG=2026.06.04 \
  --build-arg PANGEO_FISH_REF=main .
docker run --rm -p 8888:8888 pangeo-fish-notebook jupyter lab --ip 0.0.0.0
```

## Optional: also publish to Docker Hub

Set the repository variable `DOCKERHUB_IMAGE` (e.g. `pangeofish/pangeo-fish-notebook`)
and the secrets `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`.
