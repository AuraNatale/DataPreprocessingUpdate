""" In this code we stored the functions that were used in the data processing pipeline,
including a brief description of their inputs, outputs and functioning"""

import numpy as np
import pandas as pd
from collections import OrderedDict, deque
from datetime import datetime
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.seasonal import seasonal_decompose
from statsmodels.tsa.stattools import acf
from statsmodels.tsa.filters.hp_filter import hpfilter
from sklearn.ensemble import IsolationForest
#from lime.lime_tabular import LimeTabularExplainer
from sklearn.metrics import silhouette_score
from keras.models import Sequential
from keras.layers import Dense, Dropout
from keras.optimizers import Adam
from keras.models import model_from_json
from river import drift
import optuna
from connection_functions import send_alert, store_datapoint
import pickle
#import dill
import os
import config as config
import matplotlib.pyplot as plt

''''
________________________________________________________________________________________________________

GLOBAL VARIABLES AND FUNCTIONS FOR INFORMATION MANAGING 
________________________________________________________________________________________________________
'''
''' In this piece of code there are the global variables that will be used in several functions deputed to the
whole preprocessing stage. In addition 'machine' and 'KPIs' will map the tassonomy defined by topic 1, particularly only
'pure' KPIs (the one that we expect to receive directly from machines) for the actual machines present in the company 
(information extracted from the provided dataset). Future development may involve the connection with an internal tassonomy of the knowledge base in such a way to provide a dynamic adaptation
of the processing pipeline to the addition of new machines or kpi. '''

fields = [
    "time",
    "asset_id",
    "name",
    "kpi",
    "operation",
    "sum",
    "avg",
    "min",
    "max",
    "var",
]
identity = ["asset_id", "name", "kpi", "operation"]
features = ["sum", "avg", "min", "max", "var"]
b_length = 40
faulty_aq_tol = 3

machines = {
    "Large Capacity Cutting Machine 1": "ast-yhccl1zjue2t",
    "Medium Capacity Cutting Machine 1": "ast-ha448od5d6bd",
    "Large Capacity Cutting Machine 2": "ast-6votor3o4i9l",
    "Medium Capacity Cutting Machine 2": "ast-5aggxyk5hb36",
    "Medium Capacity Cutting Machine 3": "ast-anxkweo01vv2",
    "Low Capacity Cutting Machine 1": "ast-6nv7viesiao7",
    "Laser Cutter": "ast-xpimckaf3dlf",
    "Laser Welding Machine 1": "ast-hnsa8phk2nay",
    "Laser Welding Machine 2": "ast-206phi0b9v6p",
    "Assembly Machine 1": "ast-pwpbba0ewprp",
    "Assembly Machine 2": "ast-upqd50xg79ir",
    "Assembly Machine 3": "ast-sfio4727eub0",
    "Testing Machine 1": "ast-nrd4vl07sffd",
    "Testing Machine 2": "ast-pu7dfrxjf2ms",
    "Testing Machine 3": "ast-06kbod797nnp",
    "Riveting Machine": "ast-o8xtn5xa8y87",
}


# The following dictionary is organized as follows: for each type of kpi [key], the corrisponding value is a list of two elements:
# - min and max of the expected range. Current implementation involves the definition of a single range for all the machine types. 
# - operation modality that the KPI can offer.

kpi = {
    "time": [
        [0, 86400],
        ["working", "idle", "offline"],
    ],  # As indicated in the taxonomy the time is reported in seconds.
    "consumption": [[0, 500000], ["working", "idle", "offline"]],  # KWh
    "power": [[0, 200000], ["independent"]],  # KW
    "emission_factor": [[0, 3], ["independent"]],  # kg/kWh
    "cycles": [[0, 300000], ["working"]],  # number
    "average_cycle_time": [[0, 4000], ["working"]],  # seconds
    "good_cycles": [[0, 300000], ["working"]],  # number
    "bad_cycles": [[0, 300000], ["working"]],  # number
    "cost": [[0, 1], ["independent"]],  # euro/kWh
}


ML_algorithms_config = {
    "forecasting_ffnn": {
        "make_stationary": True,  # Default: False
        "detrend": False,  # Default: False
        "deseasonalize": False,  # Default: False
        "get_residuals": False,  # Default: False
        "scaler": True,  # Default: True
    },
    "anomaly_detection": {
        "make_stationary": False,  # Default: False
        "detrend": False,  # Default: False
        "deseasonalize": False,  # Default: False
        "get_residuals": False,  # Default: False
        "scaler": False,  # Default: False
    },
}


def get_batch(x, f):
    """
    Retrieve a specific batch of data for the given feature from the store.

    This function loads the Pickle file 'store.pkl' and search for the batch of data in the saved structure according
    to the identity of the kpi (extracted from x) and to the specific feature (f in ['sum', 'avg', 'min', 'max', 'var'])
    it needs to be handled.

    Arguments:
    - x (dict): The datapoint from which extract the identity of the timeseries being processed.
      Expected keys include:
        - 'name' (str): The type of the machine.
        - 'asset_id' (str): The asset identifier.
        - 'kpi' (str): The key performance indicator.
        - 'operation' (str): The operation type.
    - f (str): The feature for which the batch is requested. This should match an entry in the `features` list (['sum', 'avg', 'min', 'max', 'var'])

    Returns:
    - list: A list representing the batch data for the specified feature.

    Example:
    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
             'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> feature = 'min'
    >>> get_batch(current_datapoint, feature)
    [0.5, 0.6, 0.7, 0.8]
    """
    with open(config.STORE_PKL, "rb") as file:
        info = pickle.load(file)
    # This function will return batch
    return list(
        info[x["name"]][x["asset_id"]][x["kpi"]][x["operation"]][0][features.index(f)]
    )


def update_batch(x, f): 
    """
    Update the batch data for a specific feature in the store.

    This function loads the existing data from the Pickle file 'store.pkl', updates the specified batch by
    appending a new value, and ensures the batch does not exceed the predefined length.
    If the batch length exceeds the limit, the oldest value is removed. Finally, the updated batch is
    stored back into the Pickle file.

    Arguments:
    - x (dict): The datapoint from which extract the identity of the timeseries being processed and the values to be appended.
      Expected keys include:
        - 'name' (str): The type of the machine.
        - 'asset_id' (str): The asset identifier.
        - 'kpi' (str): The key performance indicator.
        - 'operation' (str): The operation type.
    - f (str): The feature for which the batch is being updated. This should match an entry in the `features` list (['sum', 'avg', 'min', 'max', 'var']).

    Returns:
    - None: The function modifies the Pickle file in place.

    Example:
    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
                             'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> feature = 'sum'
    >>> update_batch(x, feature)
    """
    with open(config.STORE_PKL, "rb") as file:
        info = pickle.load(file)
    dq = deque(
        info[x["name"]][x["asset_id"]][x["kpi"]][x["operation"]][0][features.index(f)]
    )
    dq.append(x[f])

    if len(dq) > b_length:
        dq.popleft()
    # Store the new batch into the info dictionary.
    info[x["name"]][x["asset_id"]][x["kpi"]][x["operation"]][0][features.index(f)] = (
        list(dq)
    )

    with open(config.STORE_PKL, "wb") as file:
        pickle.dump(info, file)


def update_counter(x, reset=False):
    """
    Update the counter for data that report problems in the acquisition.

    This function loads the existing data from the Pickle file and either increments the counter
    or resets it to zero based on the `reset` flag. The counter is associated to a specific KPI of a specific machine.

    Arguments:
    - x (dict): The datapoint from which extract the identity of the timeseries being processed.
      Expected keys include:
        - 'name' (str): The type of the machine.
        - 'asset_id' (str): The asset identifier.
        - 'kpi' (str): The key performance indicator.
        - 'operation' (str): The operation type.
    - reset (bool, optional): If `True`, the counter is reset to 0. If `False`, the counter is incremented.
      Default is `False`.

    Returns:
    - None: The function modifies the Pickle file in place.

    Example:
    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
    >>>                      'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> # counter = 1
    >>> update_counter(current_datapoint, reset=False)  # counter becomes 2
    >>> update_counter(current_datapoint, reset=True)   # counter becomes 0
    """

    with open(config.STORE_PKL, "rb") as file:
        info = pickle.load(file)
    if not reset:
        info[x["name"]][x["asset_id"]][x["kpi"]][x["operation"]][1] += 1
    else:
        info[x["name"]][x["asset_id"]][x["kpi"]][x["operation"]][1] = 0

    with open(config.STORE_PKL, "wb") as file:
        pickle.dump(info, file)


def get_counter(x):
    """
    Retrieve the current counter value for a specific KPI and machine from the Pickle file.

    This function loads the data from the Pickle file 'store.pkl' and returns the current counter
    associated with a specific combination of 'name', 'asset_id', 'kpi', and 'operation'.

    Arguments:
    - x (dict): The datapoint from which extract the identity of the timeseries being processed.
      Expected keys include:
        - 'name' (str): The type of the machine.
        - 'asset_id' (str): The asset identifier.
        - 'kpi' (str): The key performance indicator.
        - 'operation' (str): The operation type.

    Returns:
    - int: The current counter value for the specified operation.

    Example:
    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
                             'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> get_counter(current_datapoint)
    2  # Returns the current counter value for the specified operation
    """
    with open(config.STORE_PKL, "rb") as file:
        info = pickle.load(file)
    return info[x["name"]][x["asset_id"]][x["kpi"]][x["operation"]][1]


def get_model_ad(x):
    """
    Retrieve the pre-trained model for the Anomaly detector from the Pickle file.

    This function loads the data from the Pickle file 'store.pkl' and returns the last trained
    Isolation forest model for the specific KPI associated to the specific machine (information extracted
    from the passed datapoint x).

    Arguments:
    - x (dict): The datapoint from which extract the identity of the timeseries being processed.
      Expected keys include:
        - 'name' (str): The type of the machine.
        - 'asset_id' (str): The asset identifier.
        - 'kpi' (str): The key performance indicator.
        - 'operation' (str): The operation type.

    Returns:
    - ob: Isolation forest model.

    Example:
    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
                             'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> get_model_ad(current_datapoint)
    """
    with open(config.STORE_PKL, "rb") as file:
        info = pickle.load(file)
    return info[x["name"]][x["asset_id"]][x["kpi"]][x["operation"]][2]

'''
def get_model_ad_exp(x):
    
    This function is used to get the model for the LIME explainer.

    Arguments:
        x: A dictionary that contains keys to locate the entry (e.g., {'name', 'asset_id', 'kpi', 'operation'}).
    
    ex_path = f'./explainer/{x["name"]}/{x["asset_id"]}/{x["kpi"]}/{x["operation"]}.dill'
    try:
        with open(ex_path, "rb") as file:
            explainer = dill.load(file)
        return explainer
    except FileNotFoundError:
        return None
'''

def update_model_ad(x, model):
    """
    Update the model with the last trained one in the Pickle file.

    This function loads the existing data from the Pickle file and updates the model for the specific
    KPI and machine (extracted from the passed datapoint).

    Arguments:
    - x (dict): The datapoint from which extract the identity of the timeseries being processed.
      Expected keys include:
        - 'name' (str): The type of the machine.
        - 'asset_id' (str): The asset identifier.
        - 'kpi' (str): The key performance indicator.
        - 'operation' (str): The operation type.
    - model (obj): An object containing the Isolation Forest model just trained.

    Returns:
    - None: The function modifies the Pickle file in place.

   Example:
    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
                             'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> model = IsolationForest(n_estimators=200, contamination=0.01)
    >>> model.fit_predict(train_set)
    >>> update_model_ad(x, model)
    """
    with open(config.STORE_PKL, "rb") as file:
        info = pickle.load(file)
    info[x["name"]][x["asset_id"]][x["kpi"]][x["operation"]][2] = model

    with open(config.STORE_PKL, "wb") as file:
        pickle.dump(info, file)

'''

def update_model_ad_exp(x, explainer):
    
    This function is used to update the LIME explainer model.

    Arguments:
        x: A dictionary that contains keys to locate the entry (e.g., {'name', 'asset_id', 'kpi', 'operation'}).
        explainer: The LIME explainer model.

    Returns:
        None: it just save the explainer model
    
    ex_path = f'./explainer/{x["name"]}/{x["asset_id"]}/{x["kpi"]}/{x["operation"]}.dill'
    os.makedirs(os.path.dirname(ex_path), exist_ok=True)
    with open(ex_path, "wb") as file:
        dill.dump(explainer, file)

'''

def get_model_forecast(x):
    """
    Retrieve the forecast model and associated parameters from the Pickle file 'forecasting_models.pkl'.

    This function loads the Pickle file containing forecasting models and extracts the Keras model along with its parameters and statistics
    for each sub-feature.

    Arguments:
    - x (dict): The datapoint from which extract the identity of the timeseries being processed.
      Expected keys include:
        - 'name' (str): The type of the machine.
        - 'asset_id' (str): The asset identifier.
        - 'kpi' (str): The key performance indicator.
        - 'operation' (str): The operation type.

    Returns:
    - dict: A dictionary containing the Keras model, parameters, and statistics for each sub-feature.

    Example:
    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
                             'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> get_model_forecast(x)
    {
        'min': [<keras_model>, {'param1': 0.5, 'param2': 0.2}, {'mean': 2400.0, 'std': 300.0}],
        'max': [<keras_model>, {'param1': 0.7, 'param2': 0.1}, {'mean': 2500.0, 'std': 350.0}],
        ...
    }
    """
    with open(config.STORE_PKL, "rb") as file:
            info = pickle.load(file)
    model_info=info[x['name']][x['asset_id']][x['kpi']][x['operation']][3]
    models_for_subfeatures = {}
    for sub_feature, data in model_info.items():
        keras_model = model_from_json(data["model_architecture"])
        keras_model.set_weights(data["model_weights"])
        models_for_subfeatures[sub_feature] = [
            keras_model,
            data["params"],
            data["stats"],
        ]
    return models_for_subfeatures



def update_model_forecast(x, models):
    """
    Update or store models, parameters, and stats in a Pickle file.

    Arguments:
    - x: A dictionary that contains keys to locate the entry (e.g., {'name', 'asset_id', 'kpi', 'operation'}).
    - models: A dictionary where the keys are sub-features ('min', 'max', 'sum', 'avg') and
             the values are lists containing [keras_model, best_params, stats].
    - store_path: The path where the Pickle file is stored.

    Returns
    - None: This function will just save the forecasting model.
    """
    with open(config.STORE_PKL, "rb") as file:
            info = pickle.load(file)
    
    # Now, for each sub-feature, add or update the model, params, and stats
    complete_model={}
    for feature, model_info in models.items():
        keras_model, best_params, stats = model_info

        # Store model data in the dictionary
        complete_model[feature] = {
            "model_architecture": keras_model.to_json(),  # Store model architecture
            "model_weights": keras_model.get_weights(),  # Store model weights
            "params": best_params,  # Store best parameters
            "stats": stats,  # Store stats
        }
    
    info[x['name']][x['asset_id']][x['kpi']][x['operation']][3]=complete_model

    # Save the updated data back to the Pickle file
    with open(config.STORE_PKL, "wb") as file:
        pickle.dump(info, file)

    print(f"Models updated successfully in {config.STORE_PKL}")
    

'''
________________________________________________________________________________________________________

FUNCTIONS FOR DATA CLEANING
________________________________________________________________________________________________________

In this piece of code there are functions related to the validation, imputation processes and related sub-operations.'''



def check_f_consistency(x):
    """
    Check the consistency of statistical values (min, avg, max, sum) for a given data point.

    This function checks whether the provided statistical values (`min`, `avg`, `max`, `sum`)
    for a data point satisfy a basic consistency rule: `min`<= `avg`<= `max`<= `sum`).
    - If any of the relation is violated, the respective indicator of the involving features is set to `False`.
    - Missing values (NaN) for any of the statistics will also flag the respective indicator as `False`.

    Arguments:
    - x (dict): The current datapoint being processed.
        Expected keys include:
        - 'min' (float or NaN): The minimum value.
        - 'avg' (float or NaN): The average value.
        - 'max' (float or NaN): The maximum value.
        - 'sum' (float or NaN): The sum value.

    Returns:
    - list: A list of boolean values indicating if the corrisponding feature value is behaving as such:
        - index 0: Consistency for `sum`
        - index 1: Consistency for `avg`
        - index 2: Consistency for `min`
        - index 3: Consistency for `max`
      `True` indicates consistency, `False` indicates a violation of the consistency rule regarding the corrisponding feature.

    Example:
    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
                             'min': 100, 'avg': 150, 'max': 200, 'sum': 500}
    >>> check_f_consistency(x)
    [True, True, True, True]  # All values are consistent

    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working'
                             'min': 200, 'avg': 100, 'max': 400, 'sum': 500}
    >>> check_f_consistency(x)
    [False, False, True, True]  # Values are inconsistent

    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working'
                             'min': NaN, 'avg': 100, 'max': 50, 'sum': 500}
    >>> check_f_consistency(x)
    [False, False, False, True]  # Values are inconsistent

    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working'
                             'min': NaN, 'avg': 100, 'max': 50, 'sum': 10}
    >>> check_f_consistency(x)
    [False, False, False, False]  # Values are inconsistent

    >>> current_datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working'
                             'min': NaN, 'avg': NaN, 'max': NaN, 'sum': 10}
    >>> check_f_consistency(x)
    [False, False, False, True]
    """
    indicator=[True, True, True, True]
    if not pd.isna(x['min']) and not pd.isna(x['avg']):
        if x['min'] > x['avg']:
            indicator[2]=False
            indicator[1]=False
    if not pd.isna(x['min']) and not pd.isna(['max']):
        if x['min'] > x['max']:
            indicator[2]=False
            indicator[3]=False
    if not pd.isna(x['min']) and not pd.isna(x['sum']):
        if x['min'] > x['sum']:
            indicator[2]=False
            indicator[0]=False
    if not pd.isna(x['avg']) and not pd.isna(x['max']):
        if x['avg'] > x['max']:
            indicator[1]=False
            indicator[3]=False
    if not pd.isna(x['avg']) and not pd.isna(x['sum']):
        if x['avg'] > x['sum']:
            indicator[1]=False
            indicator[0]=False
    if not pd.isna(x['max']) and not pd.isna(x['sum']):
        if x['max'] > x['sum']:
            indicator[0]=False
            indicator[3]=False
    if pd.isna(x['sum']):
        indicator[0]=False
    if pd.isna(x['avg']):
        indicator[1]=False
    if pd.isna(x['min']):
        indicator[2]=False
    if pd.isna(x['max']):
        indicator[3]=False
    return indicator


def validate(x):
    """
    Takes in input the datapoint and checks its reliability in
    terms of format and check (via call to check_range(x)).
    In general, if the data point is too severly compromised (one of the identity fields is
    nan or missing, all features are nan), then it is labeled as 'Corrupted' and saved
    into the database (the label will serve to avoid considering the datapoint
    in any further processing).

    Arguments:
    - x (dict): the data point that is being processed.

    Returns (depending on the case):
    - x (dict): the datapoint eventually transformed
    - None: if the datapoint is labeled as 'Corrupted'
    - old_counter (int): if incremented signals that the point has been labeled as 'Corrupted' or transformed.
    """
    for f in fields:
        x.setdefault(
            f, np.nan
        )  # if some fields is missing from the expected ones, put a nan
    x = dict(
        OrderedDict((key, x[key]) for key in fields)
    )  # order the fields of the datapoint

    # Ensure the reliability of the field time
    if pd.isna(x["time"]):
        x["time"] = datetime.now()

    # Check that there is no missing information in the identity of the datapoint, otherwise we store in the database, labelled 'Corrupted'.
    if any(pd.isna(x.get(key)) for key in identity):
        # Future developments for updating the counter in this case.
        x["status"] = "Corrupted"
        # store_datapoint(x)
        return None
    # if the code run forward it means that the identity is intact.
    old_counter = get_counter(x)
    # print(f'old counter {old_counter}')
    # Check if all the features that the datapoint has are nan or missing.
    if all(pd.isna(x.get(key)) for key in features):
        update_counter(x)
        x["status"] = "Corrupted"
        # store_datapoint(x)
        return None, old_counter

    # if the datapoint comes here it means that it didn't miss any information about the identity and at least one
    # feature that is not nan.

    x = check_range(x)  # Here i change letter since i need x to get the counter later.

    # if the datapoint comes here it means that at least one feature value is respecting the range constraint for the
    # specific kpi.
    if x:
        # Check if the features (min, max, sum, avg) satisfy the basic logic rule min<=avg<=max<=sum
        cc = check_f_consistency(x)
        if all(not c for c in cc):  # meaning that no feature respect the logic rule
            if pd.isna(x["var"]):
                update_counter(x)
                x["status"] = "Corrupted"
                store_datapoint(x)
                return None, old_counter
        elif all(c for c in cc):  # the datapoint verifies the logic rule.
            # if now there is a nan it could be either the result of the range check or that the datapoint
            # intrinsically has these nans.
            any_nan = False
            for f in features:
                if pd.isna(x[f]):
                    any_nan = True
                    if all(pd.isna(get_batch(x, f))):
                        pass
                    else:
                        update_counter(x)
                        break
            if not any_nan:
                # it means that the datapoint is consistent and it doesn't have nan values --> it is perfect.
                update_counter(x, True)  # reset the counter.
        else:  # it means that some feature are consistent and some not. Put at nan the not consistent ones.
            for f, c in zip(features, cc):
                if not c:
                    x[f] = np.nan
            update_counter(x)
    return x, old_counter


def check_range(x):
    """
    Checks the range of features values of the datapoint in input according to
    a range that is in the dictionary kpi in \src\app\dataprocessing_funtions.py.

    Arguments:
    - x (dict): the datapoint under evaluation.

    Returns:
    - None: if all the features values fail the check range, the datapoint
    is labeled as 'Corrupted' and saved into the database.
    - x (dict): the checked datapoint, eventually transformed.
    """
    # Retrieve the specific range for the kpi that we are dealing with
    l_thr = kpi[x["kpi"]][0][0]
    h_thr = kpi[x["kpi"]][0][1]

    for k in features:
        if x[k] < l_thr:
            x[k] = np.nan
        if k in ["avg", "max", "min", "var"] and x[k] > h_thr:
            x[k] = np.nan

    # if after checking the range all features are nan --> corrupted
    if all(pd.isna(value) for value in [x.get(key) for key in features]):
        update_counter(x)
        x["status"] = "Corrupted"
        store_datapoint(x)
        return None
    else:
        return x


def check_range_ai(x):
    """
    Checks the range of features values of the datapoint in input after been imputed. The range used for
    the comparison is in the dictionary kpi in \src\app\dataprocessing_funtions.py.

    Arguments:
    - x (dict): the datapoint under evaluation.

    Returns:
    - flag: 'True' if all the datapoint's feature values pass the range check, 'False' otherwise.
    """
    flag = True  # takes trace of: has the datapoint passed the range check without being changed?
    l_thr = kpi[x["kpi"]][0][0]
    h_thr = kpi[x["kpi"]][0][1]

    for k in features:
        if x[k] < l_thr:
            flag = False
        if k in ["avg", "max", "min", "var"] and x[k] > h_thr:
            flag = False
    return flag


# ______________________________________________________________________________________________
# This function is the one that phisically make the imputation for a specific feature of the data point.
# It receives in input the univariate batch that needs to use and according to the required number of data
# needed by the Exponential Smoothing, it decides to use it or to simply adopt the maean.


def predict_missing(batch):
    """
    Predicts missing values in a batch of data passed in input.

    This function imputes missing values (`NaN`) in a batch of data.
    If the batch contains a sufficient number of values (i.e., 2*seasonality, set at 7),
    it uses an Exponential Smoothing model with seasonal and trend components to predict the missing value.
    Otherwise, it calculates the mean of the available values for imputation.

    Arguments:
    - batch (list): A list of numerical values representing a time-series batch. Missing values are represented as `NaN`.

    Returns:
    - NaN: if all the values in the batch are nan (meaning that more likely the feature value is not definable for that kpi).
    - prediction (float): The predicted value if sufficient data is available for imputation.


    Example:
        >>> import numpy as np
        >>> from statsmodels.tsa.holtwinters import ExponentialSmoothing
        >>> batch = [3.5, np.nan, 4.2, 5.1, np.nan, 6.3, 7.2, np.nan, 1.6, 2.3, 0.1, 5.2, np.nan, 9.0, 10.3]
        >>> prediction = predict_missing(batch)
        >>> print(prediction)
        4.7

    """
    seasonality = 7
    cleaned_batch = [x for x in batch if not pd.isna(x)]
    if not (all(pd.isna(x) for x in batch)) and batch:
        if len(cleaned_batch) > 2 * seasonality:
            model = ExponentialSmoothing(
                cleaned_batch, seasonal="add", trend="add", seasonal_periods=seasonality
            )
            model_fit = model.fit()
            prediction = model_fit.forecast(steps=1)[0]
        else:
            prediction = float(np.nanmean(batch))
        return prediction
    else:
        return (
            np.nan
        )  # Leave the feature as nan since we don't have any information in the batch to make the imputation. If the
        # datapoint has a nan because the feature is not definable for it, it will be leaved as it is from the
        # imputator.


def imputer(x):
    """
    Imputes missing values in a datapoint and ensures consistency with feature constraints.

    This function attempts to impute missing values in a datapoint using statistical models like Exponential Smoothing (via `predict_missing`).
    If, after the imputation, the new vlaue fails the consistency or the range check, then Last Value Carried Forward (LVCF) method is used.
    The function, also takes care of storing the new value in the batch.

    Arguments:
    - x (dict): single datapoint with feature values. Missing values are represented as `NaN`.

    Returns:
    - x (dict): The updated datapoint with imputed values and validated features.

    Example usage:
    >>> datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
    >>>                      'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> result = imputer(datapoint)
    >>> print(result)
    result = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
                         'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': 2251.5}

    """
    if x:
        if isinstance(x, tuple):
            x = x[0]
            # Because the validated datapoint may exit in the check range with 2 returned values.

        # Try imputation with mean or the HWES model.
        for f in features:
            batch = get_batch(x, f)
            if pd.isna(x[f]):
                x[f] = predict_missing(batch)

        # Check again the consistency of features and the range.
        if check_f_consistency(x) and check_range_ai(x):
            pass
        else:  # It means that the imputed data point has not passed the check on the features and on their expected range.
            # In this case we use the LVCF as a method of imputation since it ensures the respect of these conditiono (the last point in the batch has been preiovusly checked)
            for f in features:
                batch = get_batch(x, f)
                x[f] = batch[-1]

        # In the end update batches with the new data point
        for f in features:
            update_batch(x, f)

        return x


def cleaning_pipeline(x, send_alerts=True):
    """
    Processes and cleans a datapoint by validating, imputing, and sending alerts for faulty data.

    This function wraps all the cleaning stages into one pipeline, also taking care of detecting whether a transformation of the datapoint as
    occurred. If so and the number of consecutive transformations overcome a threshold (arbitrarily set at 3 in fault_aq_tol), then it triggers
    the alert.

    Arguments:
    - x (dict): A dictionary representing a single datapoint.
    - send_alerts (bool): If `True`, the function sends an alert when a faulty datapoint is detected. Default is `True`.

    Returns:
    - dict: The cleaned and imputed datapoint after processing.

    Example:
    >>> datapoint = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
    >>>                      'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': nan}
    >>> result = cleaning_pipeline(datapoint)
    >>> print(result)
    result = {'time': '2024-09-17 00:00:00+00:00', 'asset_id': 'ast-o8xtn5xa8y87', 'name': 'riveting', 'kpi': 'good_cycles', 'operation': 'working',
                         'sum': 24025.0, 'avg': 2280.0, 'min': 330.0, 'max': 1224.0, 'var': 2251.5}
    """

    validated_dp, old_counter = validate(x)
    new_counter = get_counter(x)
    if new_counter == old_counter + 1 and new_counter >= faulty_aq_tol:
        id = {key: x[key] for key in identity if key in x}
        if send_alerts:
            send_alert(id, "Nan", new_counter)
    cleaned_dp = imputer(validated_dp)

    return cleaned_dp


"""
________________________________________________________________________________________________________

FUNCTIONS FOR DRIFT DETECTION
________________________________________________________________________________________________________
 
In this piece of code there are the functions that are used in the drift detection section of the
preprocessing pipeline."""


def ADWIN_drift(x, delta=0.005, drift_threshold=3):
    """
    Detects concept drift using the ADWIN algorithm.

    Parameters:
        x (DataFrame): Input data.
        features (list): List of feature names to check for drift.
        b_length (int): Minimum required batch length.
        delta (float): Sensitivity parameter for ADWIN (default=0.005).
        drift_threshold (int): Number of feature drifts to signal overall drift (default=3).

    Returns:
        bool: True if overall drift is detected, False otherwise.
    """
    drift_count_per_f = 0

    for f in features:
        # Get the feature data (batch)
        batch = get_batch(x, f)

        if len(batch) < b_length:
            return False
        else:
            # Initialize ADWIN instance for this feature
            adwin = drift.ADWIN(delta=delta)
            # Check for drift
            for i, value in enumerate(batch):
                adwin.update(value)
                if adwin.drift_detected:
                    drift_count_per_f += 1

    if drift_count_per_f >= drift_threshold:
        return True
    else:
        return False


"""'
________________________________________________________________________________________________________
FUNCTIONS FOR ANOMALY DETECTION
________________________________________________________________________________________________________
"""

""" In this code we stored the functions that were used in the anomaly detection section of the
preprocessing pipeline, including a brief description of their inputs, outputs and functioning"""


def ad_train(historical_data):
    """
    Trains an anomaly detection model using Isolation Forest on historical data.
    The training consists in optimizing the contamination parameter using the Silhouette Score to balance cluster separation
    between the detected normal class and the anomaly class. If no acceptable Silhouette Score (> 0.70) is found,
    the contamination is set to a very low value (1e-5) since it means that no anomaly is present in the train set.
    Features with all `NaN` values are excluded, and residual missing values are imputed with zeros to ensure proper working.


    Arguments:
    - historical_data (DataFrame): a dataset containing historical feature values. Each row represents a data point, and columns correspond to features.
    Missing values are handled but data should be cleaned first to ensure valuable training.

    Returns:
    - model (obj): IsolationForest trained model.

    Example:
        >>> model = ad_train(historical_data)
        >>> print(model)
        IsolationForest(contamination=0.11, n_estimators=200)  # Example output
    """

    # account also for the case in which one feature may not be definable for a kpi

    train_set = pd.DataFrame(historical_data)[features]
    nan_columns = train_set.columns[train_set.isna().all()]
    train_set = train_set.drop(columns=nan_columns)
    train_set = train_set.fillna(0)

    s = []
    cc = np.arange(0.01, 0.5, 0.01)
    for c in cc:
        model = IsolationForest(n_estimators=200, contamination=c)
        an_pred = model.fit_predict(train_set)
        if len(set(an_pred)) > 1:  # Check for multiple clusters
            s.append(silhouette_score(train_set, an_pred))
        else:
            s.append(-1)
    if max(s) <= 0.70:
        optimal_c = 1e-5
    else:
        optimal_c = cc[np.argmax(s)]
    model = IsolationForest(n_estimators=200, contamination=optimal_c)
    model.fit_predict(train_set)
    return model

def ad_exp_train(historical_data):
    '''
    This function is used to create a LIME explainer object.

    Arguments:
    - historical_data (pandas dataframe): historical data.

    Returns:
    - explainer (obj): the LIME explainer object.
    '''
    train_set = pd.DataFrame(historical_data)
    nan_columns = train_set.columns[train_set.isna().all()]
    train_set = train_set.drop(columns=nan_columns)
    try:
        train_set = train_set.drop(columns=['time', 'asset_id', 'name', 'kpi', 'operation', 'status'])
    except KeyError:
        # columns were already removed
        pass
    train_set = train_set.fillna(0)

    explainer = LimeTabularExplainer(
        train_set.values,
        mode='classification',
        feature_names=['sum', 'avg', 'min', 'max'],
        class_names=['Normal', 'Anomaly']
        )
    return explainer


def ad_predict(x, model):
    """
    Predicts the anomaly status ('Anomaly' or 'Normal') of a datapoint using a trained Isolation Forest model.
    It calculates the anomaly probability based on the model's decision function.

    Arguments:
    - x (dict): single datapoint.
    - model (obj): the last trained model of Isolation Forest.

    Returns:
    - x (dict): the original datapoint enriched of the new field 'status': 'Anomaly/Normal'.
    - `anomaly_prob` (int): The anomaly probability as a percentage (0–100).

    Example:
        >>> status, prob = ad_predict(datapoint, model)
        >>> print(status, prob)
        Normal 85  # Example output
    """
    # account for the case in which one feature may be nan also after the imputation since the feature is not definable for that kpi.
    dp = pd.DataFrame.from_dict(x, orient="index").T
    dp = dp[features]
    # nan_columns = dp.columns[dp.isna().all()]
    # dp = dp.drop(columns=nan_columns)
    dp = dp.fillna(0)

    status = model.fit_predict(dp)
    anomaly_score = model.decision_function(dp)
    anomaly_prob = 1 - (1 / (1 + np.exp(-5 * anomaly_score)))
    anomaly_prob = int(anomaly_prob[0] * 100)
    if status == -1:
        status = "Anomaly"
    else:
        status = "Normal"
    return status, anomaly_prob

def ad_exp_predict(x, explainer, model):
    '''
    This function is used to predict the explanation for a data point.

    Arguments:
    - x (dict): a dictionary that contains the data point for which the explanation is required.
    - explainer (obj): The LIME explainer model.
    - model (obj): The anomaly detection model.

    Returns:
    - readable_output (str): The explanation for the data point (in a human readable way).
    '''
    dp=pd.DataFrame.from_dict(x, orient="index").T
    dp=dp[features].dropna(axis=1)

    class_pred = lambda x: [0.01, 0.99] if model.fit_predict([x])[0] == 1 else [0.99, 0.01]
    def predict_list(x):
        l = []
        for element in x:
            l.append(class_pred(element))
        return np.array(l)
    explanation = explainer.explain_instance(
        dp.values[0],
        predict_list,
        top_labels=1,
        num_samples=200
    )
    # readable_output = "Feature Contributions to the Prediction:\n"
    # for feature, weight in explanation.as_list(label=explanation.top_labels[0]):
    #     readable_output += f"- {feature}: {weight:.4f}\n"
    # WORDINGS FOR NON EXPERTS
    readable_output = "Here’s why the model classified this as an anomaly:\n\n"
    for feature, weight in explanation.as_list(label=explanation.top_labels[0]):
        impact = "increased the likelihood" if weight > 0 else "reduced the likelihood"
        readable_output += f"- {feature} {impact} by {abs(weight):.2f}\n"
    return readable_output

"""'
________________________________________________________________________________________________________
FUNCTIONS FOR CUSTOMED ALERTS
________________________________________________________________________________________________________
"""
""" In this code we stored the functions that were used in the streaming pipeline to manage the 
customed alerts that were set by the user."""

import os
import json
import config  # assume ALERTS_CONFIGURATION_PATH is defined in config

def check_custom_alerts(datapoint):
    """
    Checks if the datapoint (which includes 'name', 'asset_id', 'kpi', 'operation', and 'avg')
    matches an alert configuration in alerts_configuration.json.

    If it does, recall the thresholds and call a function to check if the datapoint has met
    some limit that should trigger an alert.

    :param datapoint: dict with at least keys: 
       ['name', 'asset_id', 'kpi', 'operation', 'avg']
    :return: dict with info about the triggered threshold, e.g.:
       {
         "type": "max" or "min",
         "threshold_value": ...,
         "days_tolerance": ...,
         "days_counted": ...
       }
       or None if no alert triggered
    """

    alerts_config_path = config.ALERTS_CONFIGURATION_PATH

    if not os.path.exists(alerts_config_path):
        return None

    # Load the entire alerts configuration (list of alert configs)
    try:
        with open(alerts_config_path, "r") as f:
            alerts_data = json.load(f)  # Should be a list
    except json.JSONDecodeError:
        # File is empty or corrupted
        return None

    # 3) Find a matching alert config for this datapoint
    #    We'll call this a "match" if name, asset_id, kpi, and operation all match
    match = None
    for alert_config in alerts_data:
        if (alert_config["machine_name"] == datapoint["name"] and
            alert_config["asset_id"] == datapoint["asset_id"] and
            alert_config["kpi"] == datapoint["kpi"] and
            alert_config["operation"] == datapoint["operation"]):
            match = alert_config
            break

    # If no match found, we do nothing
    if not match:
        return None

    # The thresholds dictionary in the alert config
    #    e.g. { "min_threshold": float or None, "min_days_tolerance": float or None,
    #           "max_threshold": float or None, "max_days_tolerance": float or None, ... }
    thresholds = match["thresholds"]

    # If thresholds are missing or all None, there's nothing to do
    if not thresholds:
        return None
    
    updated_thresholds, crossed_thresholds = check_limit_thresholds(thresholds, datapoint)

    match["thresholds"] = updated_thresholds

    # Save the entire alerts_data list back to the JSON file
    with open(alerts_config_path, "w") as f:
        json.dump(alerts_data, f, indent=2)

    # Return info about crossed thresholds (if any)
    return crossed_thresholds


def check_limit_thresholds(thresholds, datapoint):

    """
    Updates threshold counters for the given datapoint and checks whether any threshold
    (min or max) has been exceeded for the required number of consecutive days.

    Args:
        thresholds (dict): 
            A dictionary that can contain:
              - "max_threshold" (float or None)
              - "max_days_tolerance" (int, float, or None)
              - "min_threshold" (float or None)
              - "min_days_tolerance" (int, float, or None)
              - "above_count" (int) [counter for consecutive days above max_threshold]
              - "below_count" (int) [counter for consecutive days below min_threshold]
        datapoint (dict): 
            A dictionary with at least the key "avg" (float), representing the current data point value.

    Returns:
        tuple: (updated_thresholds, crossed_thresholds)
            - updated_thresholds (dict): The same thresholds dictionary but with possibly updated
              "above_count"/"below_count".
            - crossed_thresholds (dict or None): A dictionary containing
              {
                "type": "max" or "min",
                "threshold_value": (float),
                "days_tolerance": (int, float, or None),
                "days_counted": (int)
              }
              if a threshold was crossed, or None otherwise.
    """

    # Initialize counters if missing
    
    if "above_count" not in thresholds:
        thresholds["above_count"] = 0
    if "below_count" not in thresholds:
        thresholds["below_count"] = 0

    avg_value = datapoint["avg"]
    crossed_thresholds = None #Default

    # Check MAX threshold if set
    max_t = thresholds.get("max_threshold", None)
    max_days_tol = thresholds.get("max_days_tolerance", None)

    if (max_t is not None) and (avg_value >= max_t):
        thresholds["above_count"] += 1
        if (max_days_tol is not None and thresholds["above_count"] >= max_days_tol) or max_days_tol is None:
            crossed_thresholds = {
                "type": "above the maximum",
                "threshold_value": max_t,
                "days_tolerance": max_days_tol,
                "days_counted": thresholds["above_count"]
            }
    else:
        thresholds["above_count"] = 0
    
    #Check MIN threshold if set
    min_t = thresholds.get("min_threshold", None)
    min_days_tol = thresholds.get("min_days_tolerance", None)

    if (min_t is not None) and (avg_value <= min_t):
        thresholds["below_count"] += 1
        if (min_days_tol is not None and thresholds["below_count"] >= min_days_tol) or min_days_tol is None:
            crossed_thresholds = {
                "type": "below the minimum",
                "threshold_value": min_t,
                "days_tolerance": min_days_tol,
                "days_counted": thresholds["below_count"]
            }
    else:
        thresholds["below_count"] = 0
    

    # Return updated thresholds and crossed thresholds

    return thresholds, crossed_thresholds



"""'
________________________________________________________________________________________________________
FUNCTIONS FOR FEATURE ENGINEERING
________________________________________________________________________________________________________
"""
""" In this code we stored the functions that were used in the feature engineering section of the
preprocessing pipeline, including a brief description of their inputs, outputs and functioning"""



def feature_engineering_pipeline(dataframe, kwargs):
    """
    Performs feature engineering on the time series data.
    Depending on the input parameters (provided via kwargs), it applies operations such as making the data stationary, detrending, deseasonalizing, extracting residuals, and scaling the features.

    Arguments:
        - dataframe (DataFrame): A filtered version of the dataset for a given machine, KPI, and operation. It contains columns like sum, avg, min, max, and var, along with time-related columns.
        - kwargs (dict): A dictionary containing flags that determine the transformations to apply. The available flags are:
            'make_stationary': Make the data stationary (default is False).
            'detrend': Detrend the time series (default is False).
            'get_trend': Extract the trend from the data (default is False).
            'deseasonalize': Remove seasonality from the data (default is False).
            'get_season': Extract the season from the data (default is False).
            'get_residuals': Extract residuals from the data (default is False).
            'scaler': Apply z-score scaling to the data (default is False).

    Returns:
        - result_dataframe (DataFrame): A DataFrame with the transformed features based on the specified operations (e.g., stationary, detrended, deseasonalized, etc.) and the original time and feature columns.

    Example:
    >>> data = {
            'time': ['2024-10-17', '2024-10-18', '2024-10-19'],
            'sum': [0.175342, 0.027339, 0.000000],
            'avg': [0.001883, 0.007630, 0.000000],
            'min': [0.001000, 0.003832, 0.000000],
            'max': [0.012461, 0.002216, 0.000000],
            'var': [0.12134,, 0.23466, 0.091245]
        }
    >>> df = pd.DataFrame(data)
    >>> kwargs = {
            'make_stationary': True,
            'detrend': False,
            'get_trend': False,
            'deseasonalize': True,
            'get_season': False,
            'get_residuals': False,
            'scaler': True
        }
    >>> transformed_df = feature_engineering_pipeline(df, kwargs)

    """
    # Remove rows with unreliable 'status'
    if "status" in dataframe.columns:
        dataframe = fill_corrupted_anomalous_values(dataframe)
    

    features = ["sum", "avg", "min", "max"]
    to_add_features = []
    for feature_name in features:
        # Check if the column exists in the DataFrame
        if feature_name in dataframe.columns:

            feature = dataframe[feature_name]
            if feature.empty or feature.isna().all() or feature.isnull().all():
                print("Feature is empty (no data).")
            else:
                ## Check stationarity
                # (output is False if not stationary, True if it is, None if test couldn't be applied)
                is_stationary = adf_test(feature)

                ## Check seasonality
                # (output: period of the seasonality None if no seasonalaty was detected.
                seasonality_period = detect_seasonality_acf(feature)

                # further check in the case the seasonality pattern is complex and cannot be detected
                if seasonality_period is None:
                    # (output: period of the seasonality None if no seasonalaty was detected.
                    seasonality_period = detect_seasonality_fft(feature)

                # (output: the decomposed time series in a list, of form [trend, seasonal, residual],
                # None if it isn't sufficient data or if some error occurs.
                decompositions = seasonal_additive_decomposition(
                    feature, seasonality_period
                )

                # Make data stationary / Detrend / Deseasonalize (if needed)

                make_stationary = kwargs.get(
                    "make_stationary", False
                )  # Set default to False if not provided
                detrend = kwargs.get(
                    "detrend", False
                )  # Set default to False if not provided
                get_trend = kwargs.get(
                    "get_trend", False
                )  # Set default to False if not provided
                deseasonalize = kwargs.get(
                    "deseasonalize", False
                )  # Set default to False if not provided
                get_season = kwargs.get(
                    "get_season", False
                )  # Set default to False if not provided
                get_residuals = kwargs.get(
                    "get_residuals", False
                )  # Set default to False if not provided
                scaler = kwargs.get(
                    "scaler", False
                )  # Set default to False if not provided

                if make_stationary and (not is_stationary):
                    if decompositions is not None:
                        feature = make_stationary_decomp(feature, decompositions)
                        is_stationary = adf_test(feature.dropna())
                    
                        if not is_stationary:
                            if seasonality_period is None:
                                feature = make_stationary_diff(
                                    feature, seasonality_period=[7]
                                )  # default weekly
                            else:
                                feature = make_stationary_diff(
                                    feature, seasonality_period=[seasonality_period]
                                )
                            is_stationary = adf_test(feature.dropna())
                           
                    else:
                        if seasonality_period is None:
                            feature = make_stationary_diff(
                                feature, seasonality_period=[7]
                            )  # default weekly
                        else:
                            feature = make_stationary_diff(
                                feature, seasonality_period=[seasonality_period]
                            )
                        is_stationary = adf_test(feature.dropna())
                        

                if detrend:
                    if decompositions is not None:
                        feature = rest_trend(feature, decompositions)
                    else:
                        feature = make_stationary_diff(feature)
                        
                if get_trend:
                    if decompositions is not None:
                        feature = decompositions[0][0]
                    else:
                        _, feature = hpfilter(feature.dropna(), lamb=1600)


                if deseasonalize:
                    if decompositions is not None:
                        feature = rest_seasonality(feature, decompositions)
                    else:
                        if seasonality_period is None:
                            feature = make_stationary_diff(
                                feature, seasonality_period=[7]
                            )  # default weekly
                        else:
                            feature = make_stationary_diff(
                                feature, seasonality_period=[seasonality_period]
                            )

                if get_season:
                    seasonality_feature = feature_name + "_season"
                    if decompositions is not None:
                        #feature = rest_seasonality(feature, decompositions)
                        feature = decompositions[0][1]
                        dataframe[seasonality_feature] = np.full(len(feature), seasonality_period )
                        
                    else:
                        dataframe[seasonality_feature] = np.full(len(feature), None)
                    to_add_features.append(seasonality_feature)

                if get_residuals:
                    if decompositions is not None:
                        feature = get_residuals_func(feature, decompositions)
                        
                    else:
                        feature = make_stationary_diff(feature)
                        if seasonality_period is None:
                            feature = make_stationary_diff(
                                feature, seasonality_period=[7]
                            )  # default weekly
                        else:
                            feature = make_stationary_diff(
                                feature, seasonality_period=[seasonality_period]
                            )

                if scaler:
                    # Apply standardization (z-score scaling)
                    feature = (feature - np.mean(feature)) / np.std(feature)

            dataframe[feature_name] = feature

    result_dataframe = dataframe[["time"] + features + to_add_features]

    return result_dataframe

def fill_corrupted_anomalous_values(df):
    """
    This function checks if some datapoint is marked as 'Anomaly' or 'Corrupted'
    and if it is it uses the `predict_missing(...)` function to fullfill it
    in a more reliable way.

    Arguments:
    - df (dataframe): Dataframe.

    Returns:
    - dataframe with predicted normal values
    """

    feature_cols = ['sum', 'avg', 'min', 'max']

    # 1) Drop rows that already have NaNs in any of the feature columns
    df = df.dropna(subset=feature_cols).copy()

    # 2) Loop row by row
    for idx in df.index:
        if df.at[idx, 'status'] in ['Anomaly', 'Corrupted']:
            # For each feature, do the following:
            for feature in feature_cols:
                # Set this one cell to NaN
                df.loc[idx, feature] = np.nan

                # Convert the entire column to a Python list
                # (this 'batch' now has exactly one missing value)
                batch = df[feature].tolist()

                # Call your predict_missing function, which returns a single float or np.nan
                predicted_value = predict_missing(batch)

                # Put the predicted value back into the DataFrame
                df.loc[idx, feature] = predicted_value

    return df

def extract_features(kpi_name, machine_name, operation_name, data):
    """
    Filter the dataset for specific parameters: KPI name, machine name, and operation name.

    Arguments:
    - kpi_name (str): Name of the KPI to filter.
    - machine_name (str): Name of the machine to filter.
    - operation_name (str): Name of the operation to filter.
    - data (DataFrame): The dataset containing time-series data.

    Returns:
    - filtered_data (DataFrame): Filtered dataset sorted by time.

    Example:
    >>> filtered_data = extract_features('working_time', 'Laser Cutter', 'working', dataset)

    """
    filtered_data = data[
        (data["name"] == machine_name)
        & (data["kpi"] == kpi_name)
        & (data["operation"] == operation_name)
    ]

    filtered_data["time"] = pd.to_datetime(filtered_data["time"])
    filtered_data = filtered_data.sort_values(by="time")

    return filtered_data




def adf_test(series):
    """
    Perform the Augmented Dickey-Fuller (ADF) test to assess stationarity of a time series.
    The function returns a boolean indicating stationarity based on the p-value (< 0.05) of the statistical hypothesis test. If the series is empty or too short, it returns None.

    Arguments:
    - series (pd.Series): Time series data (can include NaN values that need to be filled).

    Returns:
    - stationarity (bool): True if the series is stationary, False otherwise.
    - None: If the series is empty or too short for the test.

    Example:
    >>> result = adf_test(time_series)
    True

    """
    if series.empty or len(series) < 2:
        # print("Series is empty or too short for ADF test.")
        return False  # Consider it non-stationary due to insufficient data

    try:
        result = adfuller(series)
        if result[1] > 0.05:
            stationarity = False
            # print("The time series is likely non-stationary.")
        else:
            stationarity = True
            # print("The time series is likely stationary.")

        # print(f"ADF Statistic: {result[0]}")
        # print(f"p-value: {result[1]}")
        # print(f"Critical Values: {result[4]}")

        return stationarity

    except Exception as e:
        # print(f"Error running ADF test: {e}")
        return None  # If error occurs, consider it non-stationary



def detect_seasonality_acf(df, max_lags=365, threshold=0.2):
    """
    Detect seasonality in a time series using Autocorrelation Function (ACF).
    The function identifies significant lags with ACF values above a specified threshold, determining the most prominent seasonality period. Returns None if no seasonality is detected.

    Arguments:
    - df (pd.Series): Time series data.
    - max_lags (int, optional): Maximum lag to analyze. Default is 365.
    - threshold (float, optional): Minimum correlation to consider significant. Default is 0.2.

    Returns:
    - int: Period corresponding to the highest significant ACF lag.
    - None: If no significant seasonality is detected.

    Example:
    >>> period = detect_seasonality_acf(time_series)
    7

    """
    # Calculate ACF
    acf_values = acf(df, nlags=max_lags, fft=True)

    # Find lags where ACF > threshold (indicating potential seasonality)
    significant_lags = (
        np.where(acf_values[1:] > threshold)[0] + 1
    )  # Find lags with ACF > threshold

    if len(significant_lags) == 0:
        return None  # No significant seasonality detected

    # Find the lag with the highest ACF value (most prominent)
    highest_acf_lag = significant_lags[np.argmax(acf_values[significant_lags])]

    if highest_acf_lag <= 1 or highest_acf_lag == len(df):
        return None  # No significant seasonality detected

    # Return the corresponding period (seasonality)
    return int(highest_acf_lag)




def detect_seasonality_fft(df):
    """
    Detect seasonality in a time series using Fast Fourier Transform (FFT).
    The function identifies the frequency with the highest magnitude, converting it into the corresponding period. Returns None if no significant seasonality is detected.

    Arguments:
    - df (pd.Series): Time series data.

    Returns:
    - period (int): Period corresponding to the dominant frequency.
    - None: If no significant seasonality is detected.

    Example:
    >>> period = detect_seasonality_fft(time_series)
    12

    """
    # Perform FFT
    fft_values = np.fft.fft(df.values)

    # Compute the magnitude of the FFT
    fft_magnitude = np.abs(fft_values)

    # Ignore the zero frequency (DC component)
    fft_magnitude[0] = 0

    # Find the frequency with the highest magnitude
    peak_frequency_index = np.argmax(fft_magnitude)
    peak_frequency = np.fft.fftfreq(len(df), d=1)[peak_frequency_index]

    # Convert the frequency to the corresponding period (seasonality period)
    if peak_frequency != 0:
        period = int(round(1 / peak_frequency))
        if period <= 1 or period == len(df):
            return None  # No significant seasonality detected
    else:
        period = None  # No significant seasonality detected

    return period





def seasonal_additive_decomposition(dataframe, period):
    """
    Decompose a time series into trend, seasonal, and residual components using an additive model.
    If sufficient data is not available or an error occurs, the function returns None.

    Arguments:
    - dataframe (pd.Series): Time series data.
    - period (int): Period of seasonality. Default is 7.

    Returns:
    - list: [trend, seasonal, residual] components.
    - None: If decomposition cannot be performed.

    Example:
    >>> decomposition = seasonal_additive_decomposition(time_series, period=12)
    [[trend], [seasonal], [residual]]

    """
    # Check if the filtered DataFrame has enough data for the decomposition
    if dataframe.empty:
        # print(f"No data found for the time serie. Skipping decomposition.")
        return None

    # Drop NaN values and check if there are enough observations
    series = dataframe.dropna()

    if len(series) < 2:  # Check if the series has at least 2 observations
        print("Not enough data. Skipping decomposition.")
        return None

    if period == None:
       return None

    if (
        len(series) < 2 * period
    ):  # Ensure enough data points for at least two full cycles
        print("Not enough data for two full cycles. Skipping decomposition.")
        return None

    # Classical decomposition (additive model)
    try:
        decomposition = seasonal_decompose(series, model="additive", period=period)

        # Plot the decomposition
        """plt.figure(figsize=(10, 8))
        decomposition.plot()
        plt.suptitle(f'Classical Decomposition of Time Series', fontsize=16)
        plt.show()"""

        # Access the individual components
        trend = decomposition.trend
        seasonal = decomposition.seasonal
        residual = decomposition.resid

        return [[trend, seasonal, residual]]

    except ValueError as e:
        # print(f"Error during decomposition: {e}")
        return None




def make_stationary_decomp(df, decompositions):
    """
    Make a time series stationary by removing trend and seasonal components.
    The function uses the provided decompositions to subtract trends and seasonalities, returning a stationary series.

    Arguments:
    - df (pd.Series): Original time series data.
    - decompositions (list): List of decompositions ([trend, seasonal, residual]).

    Returns:
    - stationary_series (pd.Series): Stationary time series.

    Example:
    >>> stationary_series = make_stationary_decomp(time_series, decompositions)

    """
    # Initialize the stationary series with the original data
    stationary_series = df.copy()
    baseline = df.median()
    # Subtract seasonal and trend components from the original data for each seasonality
    for decomposition in decompositions:
        trend = decomposition[0]
        seasonal = decomposition[1]

        # Fill NaN values in the trend with the original values (for areas where trend is NaN)
        trend_filled = trend.fillna(df)

        # Remove both trend and seasonal components for the current period
        stationary_series -= seasonal  # Subtract seasonal component
        stationary_series -= trend_filled  # Subtract trend component

    stationary_series += baseline
    return stationary_series




def make_stationary_diff(df, seasonality_period=[]):
    """
    Make a time series stationary using differencing.
    Applies first-order differencing or seasonal differencing based on the provided periods.

    Arguments:
    - df (pd.Series): Original time series data.
    - seasonality_period (list, optional): List of seasonality periods for differencing.

    Returns:
    - df_diff (pd.Series): Differenced time series.
    - None: If an error occurs.

    Example:
    >>> stationary_series = make_stationary_diff(time_series, seasonality_period=[7])

    """
    try:
        # Compute the baseline of the original series
        baseline = df.median()
        # Check if the input dataframe is empty
        if df.empty:
            raise ValueError("The input time series is empty.")

        # First-order differencing if no seasonality period is provided
        if not seasonality_period:  # No seasonality
            df_diff = df.diff().dropna()

        else:
            # Apply seasonal differencing for each period in the seasonality_period list
            for period in seasonality_period:
                if isinstance(period, (int, float)) and period > 0:
                    # Perform seasonal differencing
                    df_diff = df.diff(int(period)).dropna()
                else:
                    raise ValueError(
                        f"Invalid seasonality period: {period}. It should be a positive integer or float."
                    )

        # Add the baseline back to the differenced series
        df_diff += baseline
        return df_diff

    except Exception as e:
        print(f"Error: {e}")
        return None




def rest_trend(df, decompositions):
    """
    Remove trend components from a time series.

    Arguments:
    - df (pd.Series): Original time series data.
    - decompositions (list): List of decompositions ([trend, seasonal, residual]).

    Returns:
    - detrended_series (pd.Series): Detrended time series.

    Example:
    >>> detrended_series = rest_trend(time_series, decompositions)

    """
    # Initialize the detrended series with the original data
    detrended_series = df.copy()
    baseline = df.median()
    # Subtract seasonal and trend components from the original data for each seasonality
    for decomposition in decompositions:
        trend = decomposition[0]

        # Fill NaN values in the trend with the original values (for areas where trend is NaN)
        trend_filled = trend.fillna(df)

        # Remove trend component for the current period
        detrended_series -= trend_filled  # Subtract trend component

    detrended_series += baseline
    return detrended_series




def rest_seasonality(df, decompositions):
    """
    Remove seasonal components from a time series.

    Arguments:
    - df (pd.Series): Original time series data.
    - decompositions (list): List of decompositions ([trend, seasonal, residual]).

    Returns:
    - deseasoned_series (pd.Series): Deseasonalized time series.

    Example:
    >>> deseasoned_series = rest_seasonality(time_series, decompositions)

    """
    # Initialize the deseasoned series with the original data
    deseasoned_series = df.copy()

    # Subtract seasonal and trend components from the original data for each seasonality
    for decomposition in decompositions:
        seasonal = decomposition[1]

        # Remove both trend and seasonal components for the current period
        deseasoned_series -= seasonal  # Subtract seasonal component

    return deseasoned_series




def get_residuals_func(df, decompositions):
    """
    Extract the residual component from multiple decompositions.

    Arguments:
    - df (pd.Series): Original time series data.
    - decompositions (list): List of decompositions ([trend, seasonal, residual]).

    Returns:
    - pd.Series: Aggregated residual series.

    Example:
    >>> residual_series = get_residuals_func(time_series, decompositions)

    """
    # Ensure decompositions is not empty
    if not decompositions or len(decompositions) == 0:
        raise ValueError("Decompositions data is missing or empty.")

    # Start with the residual from the first decomposition
    residual_series = decompositions[0][
        2
    ]  # Assuming [2] is the residual component of the decomposition

    # Loop through the remaining decompositions and sum the residuals
    for decomposition in decompositions[1:]:
        residual_series += decomposition[2]  # Add residual from each decomposition

    return residual_series


"""
________________________________________________________________________________________________________
FUNCTIONS FOR FORECASTING ALGORITHM
________________________________________________________________________________________________________

In this code we stored the functions that were used in the forecasting section of the
preprocessing pipeline, including a brief description of their inputs, outputs and functioning"""


def create_sequences(data, tau):
    """
    Create sequences for a Time-Delay Neural Network (TDNN) from a time series.
    This function generates sliding window sequences of a specified length (tau) from the given time series.

    Arguments:
    - data (array): The time series data to be transformed into sequences.
    - tau (int): The length of the sliding window.
    Returns:
    - sequences (ndarray): A 2D array where each row corresponds to a sequence of length tau.

    Example:
        >>> data = [1, 2, 3, 4, 5]
        >>> tau = 3
        >>> create_sequences(data, tau)
        array([[1., 2., 3.],
            [2., 3., 4.],
            [3., 4., 5.]])

    """
    num_sequences = len(data) - tau + 1  # Number of sequences
    sequences = np.zeros((num_sequences, tau))  # Initialize matrix
    for i in range(num_sequences):
        sequences[i] = data[i : i + tau]
    return sequences


def split_data(x_data, y_data, train_size=0.8, val_size=0.1, test_size=0.1):
    """
    Split data into training, validation, and test sets.
    This function partitions input and target data into training, validation, and test subsets
    based on the specified proportions.

    Arguments:
    - x_data (array): Input data set.
    - y_data (array): Target data set.
    - train_size (float): Proportion of data to allocate for training. (default=0.8)
    - val_size (float): Proportion of data to allocate for validation. (default=0.1)
    - test_size (float): Proportion of data to allocate for testing. (default=0.1)

    Returns:
    - x_train, x_val, x_test, y_train, y_val, y_test (tuple of ndarrays): The split input and target data sets.

    Example:
    >>> x_data = np.arange(10)
    >>> y_data = np.arange(10, 20)
    >>> split_data(x_data, y_data)
    (array([0, 1, 2, 3, 4, 5, 6]), array([7]), array([8, 9]),
     array([10, 11, 12, 13, 14, 15, 16]), array([17]), array([18, 19]))

    """
    assert train_size + val_size + test_size == 1, "The splits should sum to 1"

    # Split into training, validation and test sets
    train_val_size = int(len(x_data) * train_size)  # 80% for training + validation
    x_train_val, x_test = x_data[:train_val_size], x_data[train_val_size:]
    y_train_val, y_test = y_data[:train_val_size], y_data[train_val_size:]

    # Further split the train_val set into training and validation sets
    train_size = int(
        len(x_train_val) * (train_size / (train_size + val_size))
    )  # 80% of 80% for training
    x_train, x_val = x_train_val[:train_size], x_train_val[train_size:]
    y_train, y_val = y_train_val[:train_size], y_train_val[train_size:]

    return x_train, x_val, x_test, y_train, y_val, y_test


def safe_normalize(data, mean, std):
    """
    Avoid division by zero by setting std to 1 for constant data
    Arguments:
    - data (array): The dataset to be normalized.
    - mean (float): The mean value of the training dataset.
    - std (float): The standard deviation of the training dataset.

    Returns:
    - normalized_data (array): The normalized dataset.

    Example:
    >>> data = np.array([10, 10, 10])
    >>> mean = np.mean(data)
    >>> std = np.std(data)
    >>> normalized_data = safe_normalize(data, mean, std)

    """
    std = np.where(std == 0, 1, std)
    return (data - mean) / std


def create_TDNN(hidden_units, lr):
    """
    Create a Time-Delay Neural Network (TDNN) model.
    This function initializes a TDNN model with three hidden dense layers and a final output layer.
    The model uses ReLU activation for hidden layers and Mean Squared Error (MSE) as the loss function.

    Arguments:
    - hidden_units (int): Number of neurons in each hidden layer.
    - lr (float): Learning rate for the Adam optimizer.

    Returns:
    - model (keras.Sequential): The compiled TDNN model.

    Example:
    >>> model = create_TDNN(hidden_units=128, lr=0.001)
    >>> model.summary()

    """
    model = Sequential()
    model.add(Dense(hidden_units, activation='relu'))
    model.add(Dropout(0.2))
    model.add(Dense(hidden_units, activation='relu'))
    #model.add(Dropout(0.2))
    #model.add(Dense(hidden_units, activation='relu'))
    model.add(Dense(1))
    model.compile(loss='mean_squared_error', optimizer=Adam(lr))
    return model


def training_TDNN(TDNN_model, x_train, y_train, x_val, y_val, epochs):
    """
    Train the TDNN model on the training data and evaluates its performance on the validation set.

    Arguments:
    - TDNN_model (keras.Sequential): The TDNN model to be trained.
    - x_train (ndarray): Input training data.
    - y_train (ndarray): Target training data.
    - x_val (ndarray): Input validation data.
    - y_val (ndarray): Target validation data.
    - epochs (int): Number of training epochs.

    Returns:
    - loss_validation (float): The final validation loss.

    Example:
    >>> loss_val = training_TDNN(model, x_train, y_train, x_val, y_val, epochs=50)
    >>> print(f"Validation loss: {loss_val}")

    """
    history = TDNN_model.fit(
        x_train, y_train, epochs=epochs, validation_data=(x_val, y_val), verbose=0
    )
    #print(history.history.keys())
    loss_training = history.history["loss"]
    #print("Loss training: ", loss_training[-1])
    loss_validation = history.history["val_loss"]
    #print("Loss validation: ", loss_validation[-1])
    return loss_validation[-1]


def objective_TDNN(trial, time_series):
    """
    Optimize TDNN hyperparameters using Optuna.
    It tunes parameters like sliding window length, epochs, learning rate, and hidden units.

    Arguments:
    - trial (optuna.trial.Trial): A single trial object for the study.
    - time_series (array): The time series data for training the TDNN.

    Returns:
    - val_loss (float): Validation loss for the given trial.

    Example:
    >>> study = optuna.create_study(direction='minimize')
    >>> study.optimize(lambda trial: objective_TDNN(trial, time_series), n_trials=100)
    >>> print(study.best_trial)

    """
    # Set hyperparameters ranges
    tau = trial.suggest_categorical("tau", [8, 15, 22])
    epochs = trial.suggest_int("epochs", 50, 150, step=10)
    lr = trial.suggest_categorical("lr", [0.01, 0.001, 0.0001])
    hidden_units = trial.suggest_int("hidden_units", 50, 250)
    TDNN_model = create_TDNN(hidden_units, lr)

    # Create sequences for the model
    sequences = create_sequences(time_series, tau)
    x_data = sequences[:, :-1]  # All but the last value as features
    y_data = time_series[tau - 1 :]  # The corresponding targets

    # print(x_data.shape)
    # print(y_data.shape)

    # Split data into training, validation, and test sets
    x_train, x_val, x_test, y_train, y_val, y_test = split_data(x_data, y_data)

    # Compute mean and std from training data
    x_mean = np.mean(x_train)
    x_std = np.std(x_train)
    y_mean = np.mean(y_train)
    y_std = np.std(y_train)

    # Normalize training and test data with mean and variance of the training
    x_train = safe_normalize(x_train, x_mean, x_std)
    x_val = safe_normalize(x_val, x_mean, x_std)
    y_train = safe_normalize(y_train, y_mean, y_std)
    y_val = safe_normalize(y_val, y_mean, y_std)


    # Reshape the input data to (1, num_sequences, tau)
    x_train = np.expand_dims(x_train, axis=0)  # Shape (1, num_sequences, tau)
    x_val = np.expand_dims(x_val, axis=0)  # Shape (1, num_sequences, tau)

    # Reshape target data to (1, num_sequences)
    y_train = np.expand_dims(y_train, axis=0)  # Shape (1, num_sequences)
    y_val = np.expand_dims(y_val, axis=0)  # Shape (1, num_sequences)
    # print(x_train.shape)
    # print(y_train.shape)
    # print(x_val.shape)
    # print(y_val.shape)

    # Train the model and return the validation loss
    val_loss = training_TDNN(TDNN_model, x_train, y_train, x_val, y_val, epochs)
    return val_loss


def tdnn_forecasting_training(series, n_trials=10):
    """
    Trains a Time-Delay Neural Network (TDNN) on a given time series. It uses Optuna to perform hyperparameter optimization and identifies the best TDNN model and parameters for forecasting tasks.

    Arguments:
        - series (DataFrame): A time series dataframe with a 'time' column and one of the feature columns ('min', 'max', 'sum', or 'avg').
        - n_trials (int, optional): Number of trials for Optuna's hyperparameter search. Default is 10.

    Returns:
        - best_model_TDNN (keras.Sequential): The TDNN model trained with the best hyperparameters.
        - best_params (dict): A dictionary containing the best hyperparameters ('tau', 'lr', 'epochs', 'hidden_units').
        - stats (array): An array containing the mean and standard deviation of the input (x_mean, x_std) and output (y_mean, y_std) for normalization.

    Example:
        >>> data = {
            'time': ['2024-10-17', '2024-10-18', '2024-10-19'],
            'sum': [0.175342, 0.027339, 0.000000]
            }
        >>> df = pd.DataFrame(data)
        >>> best_model, best_params, stats = tdnn_forecasting_training(df, n_trials=10)

    """
    # Extract only column associated to one of ['min', 'max', 'sum', 'avg']
    time_series = series.iloc[:, 1]

    # Create study and save best params
    TDNN_study = optuna.create_study(direction="minimize")
    TDNN_study.optimize(
        lambda trial: objective_TDNN(trial, time_series), n_trials=n_trials
    )
    best_params = TDNN_study.best_params
    # print('Best Hyperparameters:', best_params)
    tau = best_params["tau"]
    epochs = best_params["epochs"]
    hidden_units = best_params["hidden_units"]
    lr = best_params["lr"]

    # Create model with best hyperparameters
    best_model_TDNN = create_TDNN(hidden_units, lr)

    # Split time_series into input and target
    sequences = create_sequences(time_series, tau)
    x_data = sequences[:, :-1]  # All but the last value as features
    y_data = time_series[tau - 1 :]  # The corresponding targets

    # Split data into training, validation, and test sets
    x_training, x_val, x_test, y_training, y_val, y_test = split_data(x_data, y_data)

    # Compute mean and std from training data
    x_mean = np.mean(x_training)
    x_std = np.std(x_training)
    y_mean = np.mean(y_training)
    y_std = np.std(y_training)
    stats = np.array([x_mean, x_std, y_mean, y_std])

    # Normalize training and test data with training stats
    x_training = safe_normalize(x_training, x_mean, x_std)
    x_test = safe_normalize(x_test, x_mean, x_std)
    y_training = safe_normalize(y_training, y_mean, y_std)
    y_test = safe_normalize(y_test, y_mean, y_std)

    # Reshape input data to (1, num_sequences, tau)
    x_training = np.expand_dims(x_training, axis=0)  # Shape (1, num_sequences, tau)
    x_test = np.expand_dims(x_test, axis=0)  # Shape (1, num_sequences, tau)

    # Reshape target data to (1, num_sequences)
    y_training = np.expand_dims(y_training, axis=0)  # Shape (1, num_sequences)
    y_test = np.expand_dims(y_test, axis=0)  # Shape (1, num_sequences)

    # Train the model
    history = best_model_TDNN.fit(x_training, y_training, epochs=epochs, verbose=0)
    # print(history.history['loss'][-1])

    # Predict on training and test data
    y_pred_training = best_model_TDNN.predict(x_training).reshape(-1)
    y_pred_test = best_model_TDNN.predict(x_test).reshape(-1)

    # calculate MSE
    TDNN_test_MSE = best_model_TDNN.evaluate(x_test, y_test)
    #print("Test MSE: ", TDNN_test_MSE)

    # Denormalize predictions and targets for plotting
    y_pred_training = y_pred_training * y_std + y_mean
    y_pred_test = y_pred_test * y_std + y_mean
    y_training = y_training * y_std + y_mean
    y_test = y_test * y_std + y_mean

    # Get time indexes for training and test data
    time_indexes_training = series.iloc[: len(y_training.reshape(-1)), 0]

    # Calculate the starting index for the test data in the original time series
    test_start_index = len(series) - len(y_test.reshape(-1))
    time_indexes_test = series.iloc[
        test_start_index:, 0
    ]  # Get time indexes for test data

    return [best_model_TDNN, best_params, stats]


def tdnn_forecasting_prediction(
    model, tau, time_series, stats, timestamp_init=None, timestamp_end=None
):
    """
    Uses a trained TDNN model to forecast future values in a time series.

    Arguments:
    - model: The trained TDNN model.
    - tau (int): The length of the input sliding window used for the TDNN model.
    - time_series (DataFrame): A dataframe containing the 'time' column and one feature column ('min', 'max', 'sum', or 'avg').
    - stats (list): A list containing normalization statistics (x_mean, x_std, y_mean, y_std).
    - timestamp_init (str, optional): The start date for the forecast. Defaults to the day after the last timestamp in the input data.
    - timestamp_end (str, optional): The end date for the forecast. Defaults to 7 days after timestamp_init.

    Returns:
        - predictions_df (DataFrame): A DataFrame containing two columns: 'time' (forecast timestamps) and the predicted values for the specified feature.

    Example usage:
         >>> time_series = pd.DataFrame({
            'time': ['2024-10-17', '2024-10-18', '2024-10-19', ...],
            'avg': [0.001883, 0.007630, 0.000000, ...]
                })
        >>> stats = [0.0042143 , 0.00472052, 0.00417373, 0.00474381]  # Example stats [x_mean, x_std, y_mean, y_std]
        >>> model = best_model  # Use the model from tdnn_forecasting_training
        >>> tau = best_params['tau']
        >>> predictions_df = tdnn_forecasting_prediction(model, tau, time_series, stats)

    """

    x_mean, x_std, y_mean, y_std = stats
    time_series["time"] = pd.to_datetime(time_series["time"])
    series = time_series.iloc[:, 1]
    column_name = time_series.columns[1]
    initial_window = np.array(
        series[len(series) - tau + 1 :]
    )  # Use the last sequence as the initial window
    predictions = []
    current_window = (initial_window - x_mean) / x_std  # Normalize the input window

    # Get last time_stamp and add one as start index of prediction
    time_indexes = time_series.iloc[:, 0]

    # Convert time_indexes to timezone-naive datetime objects if they are timezone-aware
    time_indexes = time_indexes.dt.tz_localize(None)

    # Get the last timestamp from time_indexes if timestamp_init is not given
    if timestamp_init is None:
        timestamp_init = time_indexes.iloc[-1] + pd.DateOffset(days=1)
    else:
        timestamp_init = pd.to_datetime(timestamp_init)

    # Predict for next 7 days if timestamp_end is not given
    if timestamp_end is None:
        timestamp_end = timestamp_init + pd.DateOffset(days=7)
    else:
        timestamp_end = pd.to_datetime(timestamp_end)

    # Calculate num_prediction as difference in days
    num_predictions = int((timestamp_end - timestamp_init).days) + 1

    # Create prediction_timestamps as a Pandas DatetimeIndex
    prediction_timestamps = pd.date_range(
        start=timestamp_init, periods=num_predictions, freq="D"
    )

    if (
        time_series.iloc[:, 0].dt.tz is not None
    ):  # If original data has timezone, apply it
        if prediction_timestamps.tz is None:
            prediction_timestamps = prediction_timestamps.tz_localize(
                time_series.iloc[:, 0].dt.tz
            )
        else:
            prediction_timestamps = prediction_timestamps.tz_convert(
                time_series.iloc[:, 0].dt.tz
            )

    for _ in range(num_predictions):
        # Predict the next value
        # Reshape the input to match the model's expected input shape (1, 1, tau-1)
        next_value_norm = model.predict(current_window.reshape(1, 1, -1))
        next_value_norm = next_value_norm.reshape(-1)  # Convert to 1D array

        next_value = next_value_norm * y_std + y_mean  # Denormalize the prediction
        predictions.append(next_value)

        # Update the current window for the next prediction
        current_window = np.append(current_window[1:], (next_value - x_mean) / x_std)

    predictions_df = pd.DataFrame(
        {"time": prediction_timestamps, column_name: predictions}
    )
    return predictions_df
