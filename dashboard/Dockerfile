FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8501
ENV TWINLINE_API=http://backend:8000
CMD ["sh","-c","streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT} --server.headless true"]
