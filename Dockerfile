FROM runpod/base:0.4.0-cuda11.8.0

# The base image comes with many system dependencies pre-installed to help you get started quickly.
# Please refer to the base image's Dockerfile for more information before adding additional dependencies.
# IMPORTANT: The base image overrides the default huggingface cache location.

# --- Optional: System dependencies ---
# COPY builder/setup.sh /setup.sh
# RUN /bin/bash /setup.sh && \
#     rm /setup.sh


# Python dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY builder/requirements.in builder/requirements.in
RUN uv pip compile builder/requirements.in -o builder/requirements.txt

RUN uv pip sync builder/requirements.txt --no-cache-dir --compile-bytecode --system

# NOTE: The base image comes with multiple Python versions pre-installed.
#       It is reccommended to specify the version of Python when running your code.


# Copy the pre-downloaded model files into the image
COPY models_hub /models_hub

# Add src files (Worker Template)
ADD src .

CMD python3 -u /handler.py