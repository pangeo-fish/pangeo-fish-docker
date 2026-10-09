# pangeo-fish-docker

Docker image = [`pangeo/pangeo-notebook`](https://github.com/pangeo-data/pangeo-docker-images)
+ a dedicated conda environment `pangeo-fish` (Python 3.11) with
[pangeo-fish](https://github.com/pangeo-fish/pangeo-fish) installed, exposed in
JupyterLab as the kernel **"Python (pangeo-fish)"**.

```
ghcr.io/pangeo-fish/pangeo-fish-notebook:latest
ghcr.io/pangeo-fish/pangeo-fish-notebook:<pangeo-notebook tag>-<pangeo-fish short sha>
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
conda create -n pangeo-fish python=3.11 pip git eccodes ipykernel
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
| `repository_dispatch` (`pangeo-fish-updated`) | same, but immediately — sent by pangeo-fish on push to `main` (see [`extras/notify-docker-image.yml`](extras/notify-docker-image.yml)) |
| push to `main` of this repo | always rebuilds and pushes |
| pull request | builds and tests, does not push |
| manual (`workflow_dispatch`) | optional `force`, pangeo-notebook tag and pangeo-fish ref |

Each build runs a smoke test (`import pangeo_fish`, kernel registered) before pushing.

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
