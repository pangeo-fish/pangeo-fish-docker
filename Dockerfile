# syntax=docker/dockerfile:1
#
# pangeo-notebook + a dedicated "pangeo-fish" conda environment exposed as a
# Jupyter kernel ("Python (pangeo-fish)").
#
# Note: pangeo-notebook is itself built from pangeo/base-image, whose ONBUILD
# triggers only fire for direct children. They do NOT fire here, so this
# Dockerfile has to do everything explicitly.

ARG PANGEO_NOTEBOOK_TAG=latest
FROM pangeo/pangeo-notebook:${PANGEO_NOTEBOOK_TAG}

ARG PANGEO_NOTEBOOK_TAG
ARG PANGEO_FISH_REPO=https://github.com/pangeo-fish/pangeo-fish.git
ARG PANGEO_FISH_REF=main
ARG PYTHON_VERSION=3.11
# If pangeo-fish (or a dependency) pulls in torch, use the CPU-only wheels
# (CUDA wheels add several GB)
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

# The source is cloned outside of $HOME: on JupyterHub (pangeo-eosc) the home
# directory is a persistent volume mounted over /home/jovyan, which would hide
# anything baked into the image there.
ENV PANGEO_FISH_ENV=pangeo-fish \
    PANGEO_FISH_SRC=/srv/pangeo-fish
ENV PANGEO_FISH_PREFIX=${CONDA_DIR}/envs/${PANGEO_FISH_ENV}

LABEL org.opencontainers.image.source="https://github.com/pangeo-fish/pangeo-fish-docker" \
      org.opencontainers.image.description="pangeo-notebook with a pangeo-fish Jupyter kernel" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      io.github.pangeo-fish.pangeo-notebook-tag="${PANGEO_NOTEBOOK_TAG}"

# 1. Create the conda env (python 3.11). Binary libraries that are awkward to
#    get from PyPI (eccodes C library) and git (for the git+https dependencies)
#    come from conda-forge. ipywidgets is the kernel-side half of Jupyter
#    widgets (the JupyterLab side is already in the notebook env).
RUN mamba create -y -n ${PANGEO_FISH_ENV} \
        python=${PYTHON_VERSION} pip git eccodes ipykernel ipywidgets \
    && mamba clean -afy

# 2. Clone pangeo-fish at the requested ref (branch, tag or commit SHA).
#    The full history is kept so that setuptools_scm can compute the version.
RUN export PATH=${PANGEO_FISH_PREFIX}/bin:${PATH} \
    && git clone --filter=blob:none ${PANGEO_FISH_REPO} ${PANGEO_FISH_SRC} \
    && git -C ${PANGEO_FISH_SRC} checkout ${PANGEO_FISH_REF} \
    && git -C ${PANGEO_FISH_SRC} log -1 --format='pangeo-fish commit: %H %s'

# 3. pip install pangeo-fish (+ its dependencies) into the env
RUN export PATH=${PANGEO_FISH_PREFIX}/bin:${PATH} \
    && python -m pip install --no-cache-dir \
        --extra-index-url ${TORCH_INDEX_URL} \
        ${PANGEO_FISH_SRC} \
    && python -c "import pangeo_fish; print('pangeo_fish imported from', pangeo_fish.__file__)"

# 4. Register the kernel in the *notebook* env (where JupyterLab runs) instead
#    of with --user, which would end up in ~/.local and be hidden by the home
#    volume on JupyterHub.
RUN ${PANGEO_FISH_PREFIX}/bin/python -m ipykernel install \
        --prefix ${NB_PYTHON_PREFIX} \
        --name pangeo-fish \
        --display-name "Python (pangeo-fish)" \
    && jupyter kernelspec list
