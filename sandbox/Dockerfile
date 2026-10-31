# ClaimCheck sandbox image
#
# Build (network allowed ONLY here, to bake in test tooling):
#   docker build -t claimcheck-sandbox:latest sandbox/
#
# Runtime (enforced by sandbox.py — do not run this image without those flags):
#   docker run --rm --network none --read-only --cap-drop ALL \
#     --security-opt no-new-privileges --pids-limit 128 \
#     --memory 256m --cpus 1 --tmpfs /tmp:rw,size=64m \
#     -v <repo>:/workspace:ro claimcheck-sandbox:latest <command>

FROM python:3.11-slim

# Bake in the tools needed to run a Python project's tests with coverage.
# No compilers, no package indexes at runtime.
RUN pip install --no-cache-dir \
    "pytest>=8,<9" \
    "coverage>=7,<8"

# Non-root user; sandbox.py also passes --user, this is defense in depth.
RUN useradd --create-home --uid 1000 sandbox
USER sandbox

WORKDIR /workspace

CMD ["python", "--version"]
