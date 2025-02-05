import json

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Optional
from src.app.on_request_pipeline import get_request
from src.app.real_time.publisher import KafkaPublisher
from src.app.real_time.request import KPIStreamingRequest, KPIValidator
from src.app.real_time.message import RealTimeKPI
import os
from dotenv import load_dotenv
from src.app.connection_functions import get_next_datapoint
from src.app.dataprocessing_functions import cleaning_pipeline
import uvicorn
import asyncio
from threading import Event
import warnings

warnings.filterwarnings("ignore")

load_dotenv()

KAFKA_TOPIC_NAME = os.getenv("KAFKA_TOPIC_NAME")
KAFKA_SERVER = os.getenv("KAFKA_SERVER")
KAFKA_PORT = os.getenv("KAFKA_PORT")
BATCH_SIZE = 1000

app = FastAPI()
# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

publisher = KafkaPublisher(
    topic=KAFKA_TOPIC_NAME,
    port=KAFKA_PORT,
    servers=KAFKA_SERVER,
)

stop_event = Event()
background_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def startup_event():
    await publisher.aioproducer.start()


def start():
    print("Starting the data preprocessing API...")
    uvicorn.run("src.app.main:app", host="0.0.0.0", port=8003, reload=True)


@app.on_event("shutdown")
async def shutdown_event():
    await real_time_streaming_stop()
    if publisher.aioproducer:
        await publisher.aioproducer.stop()


@app.get("/")
def root():
    return {"message": "Data preprocessing in progress."}


@app.get("/get_request")
def get_request_callback(
        machine_name: str = Query(..., description="Name of the machine"),
        asset_id: str = Query(..., description="ID of the asset"),
        kpi: str = Query(..., description="Key Performance Indicator"),
        operation: str = Query(..., description="Type of operation"),
        timestamp_start: datetime = Query(..., description="Start timestamp in ISO format"),
        timestamp_end: datetime = Query(..., description="End timestamp in ISO format"),
        transformation: Optional[str] = Query(
            None, description="Transformation type (e.g., 'S', 'T')"
        ),
        forecasting: bool = Query(False, description="Enable forecasting (true/false)"),
):
    try:
        json_transformed_data = get_request(
            machine_name,
            asset_id,
            kpi,
            operation,
            timestamp_start,
            timestamp_end,
            transformation,
            forecasting,
        )
        return json_transformed_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/real-time/start")
async def real_time_streaming_start(kpi_streaming_request: KPIStreamingRequest):
    global background_task, stop_event
    if background_task and not background_task.done():
        return {"message": "Task is already running!"}

    stop_event.clear()

    if kpi_streaming_request.special:
        background_task = asyncio.create_task(send_special_kpis(kpi_streaming_request))
    else:
        background_task = asyncio.create_task(send_kpis(kpi_streaming_request))

    return {"message": "Background task started!"}


async def send_special_kpis(kpi_streaming_request: KPIStreamingRequest):
    global stop_event

    try:
        kpi_validator = KPIValidator.from_streaming_request(kpi_streaming_request)
    except Exception as e:
        print(f"Error initializing KPIValidator: {e}")
        return

    if not kpi_validator.check_special_request_validity():
        print("Invalid special request. No 1:1 mapping between KPIs and operations. Exiting...")
        return

    # { kpi: (aggregation_column, [values], operation) }. One value for each machine - single operation pairs
    accumulated_data = {kpi + "_" + operation: ("", []) for kpi, operation in
                        zip(kpi_validator.kpis, kpi_validator.operations)}

    iterator = get_next_datapoint(kpi_validator)

    while not stop_event.is_set():
        try:
            # Fetch and process the data point
            raw_data = next(iterator)
            cleaned_data = cleaning_pipeline(raw_data, send_alerts=False)

            if cleaned_data is None:
                print(f"Data point could not be fetched. Skipping...")
                continue

            if kpi_validator.validate(cleaned_data):
                kpi_name = cleaned_data["kpi"]
                operation = cleaned_data["operation"]
                key = kpi_name + "_" + operation
                aggregation_column = kpi_validator.get_aggregation_from_kpi(kpi_name)
                accumulated_data[key] = (
                    aggregation_column,
                    accumulated_data[key][1] + [cleaned_data[aggregation_column]],
                )

            # Check readiness of all KPIs
            if all(
                    len(values) == kpi_validator.machine_count
                    for (_, values) in accumulated_data.values()
            ):
                message = []
                for full_key, (column, values) in accumulated_data.items():
                    kpi, operation = full_key.split("_")
                    message.append(RealTimeKPI(kpi, column, values, operation).to_json())
                    accumulated_data[full_key] = ("", [])
                await publisher.aioproducer.send_and_wait(
                    publisher._topic, json.dumps(message).encode("utf-8")
                )

                await asyncio.sleep(1)

        except Exception as e:
            print(f"Error in loop: {e}")
            stop_event.set()
            break

    print("Exiting KPI streaming loop.")


async def send_kpis(kpi_streaming_request: KPIStreamingRequest):
    global stop_event

    try:
        kpi_validator = KPIValidator.from_streaming_request(kpi_streaming_request)
    except Exception as e:
        print(f"Error initializing KPIValidator: {e}")
        return

    accumulated_data = {kpi: ("", []) for kpi in kpi_validator.kpis}

    iterator = get_next_datapoint(kpi_validator)

    while not stop_event.is_set():
        try:
            # Fetch and process the data point
            raw_data = next(iterator)
            cleaned_data = cleaning_pipeline(raw_data, send_alerts=False)

            if cleaned_data is None:
                print(f"Data point could not be fetched. Skipping...")
                continue

            kpi_name = cleaned_data["kpi"]
            if kpi_validator.validate(cleaned_data):
                aggregation_column = kpi_validator.get_aggregation_from_kpi(kpi_name)
                accumulated_data[kpi_name] = (
                    aggregation_column,
                    accumulated_data[kpi_name][1] + [cleaned_data[aggregation_column]],
                )

            # Check readiness of all KPIs
            if all(
                    len(data[1]) == kpi_validator.machine_count
                    for data in accumulated_data.values()
            ):
                message = [
                    RealTimeKPI(kpi, column, values, "").to_json()
                    for kpi, (column, values) in accumulated_data.items()
                ]
                for kpi in accumulated_data.keys():
                    accumulated_data[kpi] = ("", [])
                await publisher.aioproducer.send_and_wait(
                    publisher._topic, json.dumps(message).encode("utf-8")
                )

                await asyncio.sleep(1)

        except Exception as e:
            print(f"Error in loop: {e}")
            stop_event.set()
            break

    print("Exiting KPI streaming loop.")


@app.get("/real-time/stop")
async def real_time_streaming_stop():
    """Stop the background task."""
    global stop_event, background_task

    if not background_task or background_task.done():
        return {"message": "No KPI streaming in progress to stop."}

    print("Stopping the real-time streaming...")
    stop_event.set()  # Signal to stop the task
    await background_task  # Wait for the task to finish

    return {"message": "KPI Streaming stopped!"}


@app.get("/health/")
def health_check():
    return {"status": "ok"}
