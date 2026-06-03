FROM quay.io/cdis/jupyter-superslim:master

LABEL name="jupyterlab-gpu-multiarch"

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Circumvent SSL issues by predownload data files (for full-data demos)
# Can remove this when batched embedding download enables faster data loading
ADD "https://uchicago.box.com/shared/static/k8z0kip2pej2v62pwgymdm45gt7dq0yw.h5" ./with-all-data/data/hist.h5
ADD "https://uchicago.box.com/shared/static/hr82b5c9g3h4y8c7avrnbgvhgdcoetld.h5" ./with-all-data/data/expr.h5
ADD "https://uchicago.box.com/shared/static/liwt3vlvdpmbfsa21wqboshh9nv6enm2.h5" ./with-all-data/data/summ.h5
RUN chmod -R 777 ./with-all-data

# Install linux dependencies for building python wheels
RUN yum install -y python3-devel gcc gcc-c++ git && yum clean all && rm -rf /var/cache/yum

USER ${NB_UID}
WORKDIR /home/${NB_USER}
EXPOSE 8888

# Copy demo materials
COPY demos/ ./

# Install python dependencies
RUN pip install -r requirements.txt \
 && pip cache purge

ENTRYPOINT ["/tini", "-g", "--"]
CMD ["start-notebook.sh"]
