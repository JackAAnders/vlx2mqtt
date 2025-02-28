FROM python:buster
#RUN apk update

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --upgrade pip

COPY ./requirements.txt .
RUN pip install -r requirements.txt

#ENV PYTHONUNBUFFERED 1
COPY . .

