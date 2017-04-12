FROM fedora

RUN dnf -y update && dnf clean all
RUN dnf -y install python3-pip && dnf clean all

EXPOSE 5000
ENV FLASK_APP dugrid
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

ENV DATABASE="/data/dugrid.db"
RUN mkdir /data && chmod a+rwx /data
VOLUME ["/data"]

WORKDIR /srv
ADD requirements.txt /srv/
RUN pip3 install --requirement requirements.txt

ADD . /srv/
RUN pip3 install .

CMD ["/srv/run.sh"]
