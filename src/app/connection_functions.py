import json
import os
import pandas as pd
import config as config
from datetime import timedelta
from notification.mail_sender import MailSender
from real_time.request import KPIStreamingRequest, KPIValidator
import requests



def get_datapoint(i):
    """
    Retrieves a specific datapoint from the dataset 'original_adapted_dataset.json' in \data.
    The stream is assumed to start from 16/09/2024, thus from index 38,400 onwards.

    Arguments:
    - i (int): The index of the desired datapoint within the truncated data stream.

    Returns:
    - datapoint (dict): the new datapoint of the stream.

    Example:
        >>> i = 5
        >>> datapoint = get_datapoint(i)
        >>> print(datapoint)
        {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'Riveting Machine', 'kpi': 'average_cycle_time', 'operation': 'working',
        'sum': nan, 'avg': 1.8807104020608367, 'min': 1.658396446642954, 'max': 1.9876466725348092, 'var': nan, 'status': nan} # Example output
    """

    with open(config.ORIGINAL_ADAPTED_DATA_PATH, "r") as file:
        stream = json.load(file)

    stream = pd.DataFrame(stream)[38400:]
    stream=stream[stream['name']=='Large Capacity Cutting Machine 1']
    datapoint = stream.iloc[i].to_dict()

    return datapoint


def get_next_datapoint(kpi_validator: KPIValidator, file=config.CLEANED_PREDICTED_DATA_PATH):
    """
    This function yields the next datapoint from the dataset

    :param kpi_validator: The request object containing the kpis, machines and operations
    :param file: The file containing the dataset
    :return: The next datapoint
    """
    data = pd.read_json(file)
    data = data[data['kpi'].isin(kpi_validator.kpis)]
    data = data[data['name'].isin(kpi_validator.machines)]
    data = data[data['operation'].isin(kpi_validator.operations)]

    # yield each record
    for index, row in data.iterrows():
        yield row.to_dict()


def get_historical_data(machine_name, asset_id, kpi, operation, timestap_start, timestamp_end):
    
    """
    This function calls the database to extract a filtered version of the dataset given the
    requested parameters

    :param machine_name: The requested machine
    :param asset_id: The requested asset_id
    :param kpi: The requested kpi
    :param operation: The requested operation
    :param timestap_start: The requested timestamp from where the time range begins
    :param timestamp_end: The requested timestamp from where the time range ends
    :return: The filtered dataframe
    """
    
    url_db = "http://localhost:8002/" 
    

    params = { 
    "start_date": timestap_start, 
    "end_date": timestamp_end, 
    "kpi_name": kpi, 
    "column_name": "",
    "machines": machine_name, 
    "operations": operation, 
    "asset_id": asset_id 
    } 
 
    # Send the GET request 
    response = requests.get(url_db + "get_real_time_data", json=params) 
 
    return response.json()["data"]


def get_historical_data_mock(machine_name, asset_id, kpi, operation, timestamp_start, timestamp_end):
    with open(config.HISTORICAL_DATA_PATH, "r") as file:
        historical = json.load(file)
    historical_data = pd.DataFrame(historical)

    historical_data = historical_data[
    (historical_data['name'] == machine_name) &
    (historical_data['asset_id'] == asset_id) &
    (historical_data['kpi'] == kpi) &
    (historical_data['operation'] == operation) &
    (historical_data['status'] != 'Corrupted') &
    (historical_data['status'] != 'anomaly')].reset_index(drop=True)


    historical_data['time'] = pd.to_datetime(historical_data['time'])

    #here we are isolating the specific timeseries that we want by filtering the historical data we have stored.
    if timestamp_end == -1:
        timestamp_end = historical_data['time'].iloc[-1]

    if timestamp_start == -1:
        timestamp_start = timestamp_end - timedelta(days=100)

    historical_data = historical_data[
        (historical_data['time'] >= timestamp_start) &
        (historical_data['time'] <= timestamp_end)]

    historical_data['time'] = historical_data['time'].astype(str)

    return historical_data


def send_alert(identity, type, counter=None,
               probability=None):  #the identity returns the type of Kpi and machine for which the anomaly/nan values
    # have been detected, type is 'Anomaly' or 'Nan', counter (is the number of consecutive days in
    # which we have detected nan) is None if type = 'Anomaly'

    """
    Sends an email alert for detected anomalies or persistent NaN values in a machine's KPI.

    Arguments:
    - identity (dict): Details about the machine and KPI, including:
        - `name`, `asset_id`, `kpi`, `operation` (all required).
        - `explanation`: Required for anomalies and customed alerts.
    - type (str): Type of issue detected ('Anomaly', 'Customed Alert', or 'Nan').
    - counter (int, optional): Consecutive days with NaN values (required if `type == 'Nan'`).
    - probability (int, optional): Anomaly probability in percentage (required if `type == 'Anomaly'`).

    Returns:
    - None
    """
    if type == 'Anomaly':
        object = 'Anomaly alert'
        alert = f"Alert anomaly in machine: '{identity['name']}' - asset: '{identity['asset_id']}' - kpi: '{identity['kpi']}' - operation: '{identity['operation']}'! The probability that this anomaly is correct is {probability}%.\n\n{identity['explanation']}"
    elif type == 'Customed Alert':
        object = 'Customed alert'
        alert = f"Alert in machine: '{identity['name']}' - asset: '{identity['asset_id']}' - kpi: '{identity['kpi']}' - operation: '{identity['operation']}'! {identity['explanation']}"
    else:
        object = 'Malfunctioning alert'
        alert = f"It has been {counter} days that machine: '{identity['name']}' - asset: '{identity['asset_id']}' returns NaN values in kpi: '{identity['kpi']}' - operation: '{identity['operation']}'. Possible malfunctioning either in the acquisition system or in the machine!"

    config.MAILER.send_mail(object, alert)



def set_alert(machine_name, asset_id, kpi, operation, thresholds):
    """
    This function is called from the GUI and sets the alert for the machine,
    asset_id, kpi, and operation given thresholds selected by the user.

    :param machine_name: The machine name
    :param asset_id: The asset ID
    :param kpi: The KPI name
    :param operation: The operation
    :param thresholds: A dictionary defining thresholds for min/max values and
                       the tolerance days before notification

    :return: None
    """

    # Path to the alerts config file
    alerts_config_path = config.ALERTS_CONFIGURATION_PATH

    # Ensure the file exists, or initialize an empty list if not
    if not os.path.exists(alerts_config_path):
        with open(alerts_config_path, "w") as f:
            json.dump([], f, indent=2)

    # Load current alert configurations
    with open(alerts_config_path, "r") as f:
        try:
            alerts_data = json.load(f)
        except json.JSONDecodeError:
            # If file is corrupted or empty, reset to empty list
            alerts_data = []

    # Create the new alert entry
    new_alert_config = {
        "machine_name": machine_name,
        "asset_id": asset_id,
        "kpi": kpi,
        "operation": operation,
        "thresholds": thresholds
    }

    updated = False
    for alert in alerts_data:
        if (alert["machine_name"] == machine_name and
            alert["asset_id"] == asset_id and
            alert["kpi"] == kpi and
            alert["operation"] == operation):
            alert["thresholds"] = thresholds
            updated = True
            break

    if not updated:
        alerts_data.append(new_alert_config)

    # Write updated configurations back to file
    with open(alerts_config_path, "w") as f:
        json.dump(alerts_data, f, indent=2)

    return f"Alert configuration set for machine '{machine_name}' (asset_id={asset_id}, kpi={kpi}, operation={operation})"


def get_alert(machine_name, asset_id, kpi, operation):
    """
    Checks if an alert configuration for the given machine_name, asset_id, kpi, operation exists.
    If it does, returns the thresholds dictionary; otherwise returns None.

    :param machine_name: str - The machine name
    :param asset_id: str or int - The asset ID
    :param kpi: str - The KPI name
    :param operation: str - The operation
    :return: dict or None - The thresholds dict if the alert exists, else None
    """
    alerts_config_path = config.ALERTS_CONFIGURATION_PATH
    
    # If the file does not exist, there are no alerts.
    if not os.path.exists(alerts_config_path):
        return None

    # Load current alert configurations
    try:
        with open(alerts_config_path, "r") as f:
            alerts_data = json.load(f)  # Should be a list
    except (json.JSONDecodeError, FileNotFoundError):
        alerts_data = []

    # Search for the matching alert
    for alert in alerts_data:
        if (alert["machine_name"] == machine_name and
            alert["asset_id"] == asset_id and
            alert["kpi"] == kpi and
            alert["operation"] == operation):
            return alert["thresholds"]  # Return only the thresholds

    # If no match found
    return None


def delete_alert(machine_name, asset_id, kpi, operation):
    """
    Deletes the alert configuration (if any) for the given machine_name, asset_id, kpi, operation.

    :param machine_name: str - The machine name
    :param asset_id: str or int - The asset ID
    :param kpi: str - The KPI name
    :param operation: str - The operation
    :return: str - A message indicating whether an alert was deleted or not found
    """
    alerts_config_path = config.ALERTS_CONFIGURATION_PATH
    
    # If the file doesn't exist, there's nothing to delete
    if not os.path.exists(alerts_config_path):
        return "No alerts file found. Nothing to delete."

    # Load current alert configurations
    try:
        with open(alerts_config_path, "r") as f:
            alerts_data = json.load(f)  # list of alert configs
    except (json.JSONDecodeError, FileNotFoundError):
        alerts_data = []

    # Look for the matching alert
    alert_found = False
    new_alerts_data = []

    for alert in alerts_data:
        if (alert["machine_name"] == machine_name and
            alert["asset_id"] == asset_id and
            alert["kpi"] == kpi and
            alert["operation"] == operation):
            alert_found = True
            # Skip this alert to effectively remove it
        else:
            new_alerts_data.append(alert)

    if alert_found:
        # Write the updated list to the file
        with open(alerts_config_path, "w") as f:
            json.dump(new_alerts_data, f, indent=2)
        return f"Alert for machine '{machine_name}' (asset_id={asset_id}, kpi={kpi}, operation={operation}) deleted."
    else:
        return "Alert not found. Nothing was deleted."


def store_datapoint(new_datapoint):

    url_db = "http://localhost:8002/"
    try:
        response = requests.post(f"{url_db}store_datapoint", json=new_datapoint)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.json()  # Return JSON response from the server
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to store data point: {e}"}



# def store_datapoint(new_datapoint):
#     """
#     Stores a new datapoint in both the current and historical data files.

#     Arguments:
#     - new_datapoint (dict): The new datapoint to be stored.

#     Returns:
#     - None
#     """

#     with open(config.NEW_DATAPOINT_PATH, "w") as json_file:
#         json.dump(new_datapoint, json_file, indent=1)

#     with open(config.HISTORICAL_DATA_PATH, "r") as file:
#         historical = json.load(file)
#     historical = pd.DataFrame(historical)
#     historical = pd.concat([historical, pd.DataFrame([new_datapoint])], ignore_index=True)

#     with open(config.NEW_DATAPOINT_PATH, "w") as file:
#         json.dump(historical.to_dict(), file, indent=1)

