# Data Processing Block

The Data Processing Block is a Python library that provides the core logic for the processing of data coming in streaming (collected by sensors in real time) or extracted from the database of historical data stored in the application. Therefore its functioning is based on two core files: "streaming_pipeline.py" for the streaming data and "on_request_pipeline.py" that allows to perform forecasting or data transformation based on historical data whenever the user requests it from the GUI.



## 📁 Repository Contents

The repository contains the following files and directories

```
📂 data-preprocessing-
├── 📂 data
│   ├── ⛁ cleaned_predicted_dataset.json
│   ├── ⛁ historical_dataset.json
│   ├── ⛁ new_datapoint.json
│   ├── ⛁ original_adapted_dataset.json
│   └── ⊞ store.pkl
├── 📂 docs
│   └── 📖 index.html
├── 📂 src
│   ├── 📂 app
│   │   ├── 📂 explainability
│   │   │   └── 📖 explainability.html 
|   |   ├── 📂 notification
│   │   │   └── 📤 mail_sender.py
│   │   │   ├── 📤 publisher.py
│   │   │   └── 📩 request.py
|   |   ├── 📂 real_time
│   │   │   ├── 📖 message.py
│   │   │   ├── 📩 kpi_request.py
│   │   │   └── 📤 kpi_response.py
│   │   ├── 🤖 config.py
│   │   ├── 🤖 connection_functions.py
│   │   ├── 🤖 dataprocessing_functions.py
│   │   ├── 🤖 fix_data.py
│   │   ├── 🤖 initialize.py
│   │   ├── 🤖 streaming_pipeline.py
│   │   ├── 🌐 main.py
│   │   ├── ⚡ on_request_pipeline.py
│   │   └── ⚡ streaming_pipeline.py
│   └── 📂 tests
│       └── 🧪 api_test.py
├── 🔄 .gitignore
├── 🐳 Dockerfile
├── 📖 README.md
├── 🛠 poetry.lock
└── 🛠 pyproject.toml
```

## 📁 Repository Contents

The repository contains the following files and directories:

- **`📂 data`**  
   A directory containing datasets used in the project.
   - **`⛁ cleaned_predicted_dataset.json`**  
      A JSON file containing the cleaned and predicted dataset.
   - **`⛁ historical_dataset.json`**  
      A JSON file containing historical data.
   - **`⛁ new_datapoint.json`**  
      A JSON file containing new data points.
   - **`⛁ original_adapted_dataset.json`**  
      A JSON file containing the original adapted dataset.
   - **`⊞ store.pkl`**  
      A pickle file for storing serialized data or models.

- **`📂 docs`**  
   A directory containing documentation files.
   - **`📖 index.html`**  
      An HTML file providing the project documentation.

- **`📂 src`**  
   A directory containing the source code.
   - **`📂 app`**  
      A directory containing the main application logic.
      - **`📂 explainability`**  
         A directory with explainability-related files.
         - **`📖 explainability.html`**  
            An HTML file providing an explanation of the methods used.
      - **`📂 notification`**  
         A directory with notification-related logic.
         - **`📤 mail_sender.py`**  
            A Python script to send notification emails.
         - **`📤 publisher.py`**  
            A Python script for publishing results.
         - **`📩 request.py`**  
            A Python script that handles KPI requests.
      - **`📂 real_time`**  
         A directory containing real-time data processing logic.
         - **`📖 message.py`**  
            A Python script for handling messages.
         - **`📩 kpi_request.py`**  
            A Python script for processing KPI requests in real time.
         - **`📤 kpi_response.py`**  
            A Python script for processing KPI responses in real time.
      - **`🤖 config.py`**  
         A Python script containing configuration settings.
      - **`🤖 connection_functions.py`**  
         A Python script with functions for connecting to external services or databases.
      - **`🤖 dataprocessing_functions.py`**  
         A Python script with utility functions for data processing.
      - **`🤖 fix_data.py`**  
         A Python script for data cleaning and fixing issues.
      - **`🤖 initialize.py`**  
         A Python script that initializes the application.
      - **`🤖 streaming_pipeline.py`**  
         A Python script defining the streaming data pipeline.
      - **`🌐 main.py`**  
         The main entry point for the application.
      - **`⚡ on_request_pipeline.py`**  
         A Python script defining the pipeline for processing incoming requests.
      - **`⚡ streaming_pipeline.py`**  
         Another Python script for handling streaming data pipelines.

   - **`📂 tests`**  
      A directory containing test scripts.
      - **`🧪 api_test.py`**  
         A Python script with unit tests for the API.

- **`🔄 .gitignore`**  
   A file specifying which files Git should ignore.
- **`🐳 Dockerfile`**  
   A file containing the Docker configuration to containerize the application.
- **`📖 README.md`**  
   The README file containing information about the project, setup instructions, and more.
- **`🛠 poetry.lock`**  
   A lock file generated by Poetry to ensure consistent dependency versions.
- **`🛠 pyproject.toml`**  
   The Poetry configuration file specifying project dependencies and metadata.


---

## 🚀 Getting Started

### Prerequisites

- Docker should be installed on your machine.
- Git should be installed on your machine.
- The [database](https://github.com/Kreative-Performative-Individuals/smart-industrial-database) container should be running

---

### Cloning the Repository

Clone this repository to your local machine running

```bash
git clone https://github.com/Kreative-Performative-Individuals/data-preprocessing-.git
cd data-preprocessing-
```

This will create a new directory named `data-preprocessing-` in your current working directory and navigate you into it.

### Docker Instructions

Build and run the container using the following commands

```bash
docker build --tag data_preprocessing .
```

```bash
 docker run --rm --name data-preprocessing- -p 8003:8003 data_preprocessing 
```

This command will start a new Docker container named `data-preprocessing-` and expose the application on port `8000`.

You can now access the Data Preprocessing API by visiting `http://localhost:8000` in your web browser or using tools like Postman.

To stop the running container, run 

```bash
docker stop data-preprocessing-
```

Since once stopped, the container is automatically deleted by `--rm`, we can just delete its image

```bash
docker rmi data_preprocessing
```



---

