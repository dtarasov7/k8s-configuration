ARG BASE_IMAGE=molecule_local/redos:7.3.6
FROM ${BASE_IMAGE}
# Build context must contain the pinned CPython 3.8 PyYAML wheel downloaded
# separately. The role itself never installs execution dependencies.
COPY PyYAML-6.0.2-*.whl /tmp/kam-pyyaml.whl
RUN /usr/bin/python3 -m zipfile -e /tmp/kam-pyyaml.whl /usr/lib/python3.8/site-packages \
    && rm /tmp/kam-pyyaml.whl \
    && /usr/bin/python3 -c "import yaml; assert yaml.__version__ == '6.0.2'"
