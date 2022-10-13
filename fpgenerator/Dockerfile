FROM python:3.10-slim-buster
RUN apt-get update && apt-get install -y cifs-utils  git shntool ffmpeg libdiscid0

WORKDIR /home/fpgenerator
COPY requirements.txt /home/fpgenerator/requirements.txt
RUN pip3 install -r requirements.txt

ARG medialib_bld_ver="unknown"
RUN echo "fpgenerator build ver is ${medialib_bld_ver}"
RUN medialib_bld_ver=${medialib_bld_ver} git clone https://github.com/Igorigorizh/MediaLibFpGenerator.git
WORKDIR /home/fpgenerator/MediaLibFpGenerator
ENV PYTHONPATH="$PYTHONPATH:./fpgenerator"