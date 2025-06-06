FROM python:3.11-slim

WORKDIR /usr/src/app

COPY requirements.txt ./
# RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y \
    build-essential \
    libmupdf-dev \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
