ARG BASE_IMAGE=molecule_local/redos:7.3.6
FROM ${BASE_IMAGE}
COPY kubectl /usr/local/bin/kubectl
RUN chmod 0755 /usr/local/bin/kubectl && /usr/local/bin/kubectl version --client --output=json
# PyYAML is used by the test harness, not by the role runtime.
COPY PyYAML-6.0.2-*.whl /tmp/kam-pyyaml.whl
RUN /usr/bin/python3 -m zipfile -e /tmp/kam-pyyaml.whl /usr/lib/python3.8/site-packages \
    && rm /tmp/kam-pyyaml.whl \
    && /usr/bin/python3 -c "import yaml; assert yaml.__version__ == '6.0.2'"
