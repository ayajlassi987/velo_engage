FROM python:3.11-slim
WORKDIR /app
COPY . ./ehr_emulator/
RUN pip install fastapi uvicorn sqlalchemy httpx pydantic
EXPOSE 8090
CMD ["uvicorn", "ehr_emulator.main:app", "--host", "0.0.0.0", "--port", "8090"]