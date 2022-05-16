FROM python:3.8.12-alpine3.14
COPY entry.pyc /entry.pyc
RUN pip3 install requests jsonschema && rm -r /root/.cache

ENTRYPOINT ["python3","/entry.pyc"]
