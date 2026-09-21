FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY unitracker ./unitracker
ENV PYTHONUNBUFFERED=1 STATE_PATH=/data/state.json
CMD ["python", "-m", "unitracker"]
