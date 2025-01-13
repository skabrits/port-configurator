FROM python:3.11

RUN apt update && apt install -y firefox-esr

COPY src/requirements.txt .

RUN pip install -r requirements.txt

WORKDIR /app

COPY src .

ENV PORT_PROVIDER="Nginx"
EXPOSE 443

CMD ["bash", "startup.sh"]