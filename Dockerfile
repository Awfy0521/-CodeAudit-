FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Use start() instead of dev() — reload mode is not suitable for containers
CMD ["python", "-c", "from main import start; start()"]
