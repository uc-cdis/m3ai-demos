FROM quay.io/cdis/jupyter-superslim:master

LABEL name="jupyterlab-gpu-multiarch"

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install linux dependencies for building python wheels
RUN yum install -y python3-devel gcc gcc-c++ git && yum clean all && rm -rf /var/cache/yum

USER ${NB_UID}
WORKDIR /home/${NB_USER}
EXPOSE 8888

# Install python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
 && pip cache purge

# Copy demo materials
COPY demos/ ./

ENTRYPOINT ["/tini", "-g", "--"]
CMD ["start-notebook.sh"]
