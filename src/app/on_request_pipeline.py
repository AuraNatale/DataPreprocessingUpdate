from dataprocessing_functions import tdnn_forecasting_prediction, feature_engineering_pipeline, get_model_forecast
from connection_functions import get_historical_data, get_historical_data_mock
import pandas as pd
import numpy as np
import json


def get_request(
    machine_name,
    asset_id,
    kpi,
    operation,
    timestap_start,
    timestamp_end,
    selected_analysis
):

    transformation_config = {
        "make_stationary": False,  # Default: False
        "detrend": False,  # Default: False
        "get_trend": False,  # Default: False
        "deseasonalize": False,  # Default: False
        "get_season": False,  # Default: False
        "get_residuals": False,  # Default: False
        "scaler": False,  # Default: False
    }

    if selected_analysis == "F":
        # transformation_config['make_stationary'] = True
        # transformation_config['scaler'] = True

        historical_data = get_historical_data_mock(
            machine_name, asset_id, kpi, operation, "", ""
        )  ## CONNECTION WITH API

        # transformed_data = feature_engineering_pipeline(historical_data, transformation_config)

        forecasting_model_info = get_model_forecast(historical_data.iloc[-1])

        data_predictions = []
        # for feature_name, feature_model_info in models.items():
        for feature_name, feature_model_info in forecasting_model_info.items():
            if feature_name in historical_data.columns:
                feature = historical_data[["time", feature_name]]
                if not (
                    feature[feature_name].empty
                    or feature[feature_name].isna().all()
                    or feature[feature_name].isnull().all()
                ):
                    forecasting_model = feature_model_info[0]
                    forecasting_params = feature_model_info[1]
                    forecasting_stats = feature_model_info[2]
                    predictions = tdnn_forecasting_prediction(
                        forecasting_model,
                        forecasting_params["tau"],
                        feature,
                        forecasting_stats,
                        timestap_start,
                        timestamp_end,
                    )
                    data_predictions.append(predictions)

        data_predictions = pd.concat(data_predictions, axis=1)


        # Drop the duplicate 'time' column after concatenation 
        data_predictions = data_predictions.loc[
            :, ~data_predictions.columns.duplicated()
        ]


        json_predictions = data_predictions.to_json(orient="records")

        #return json_predictions
        return data_predictions

    else:
        historical_data = get_historical_data_mock(
            machine_name, asset_id, kpi, operation, timestap_start, timestamp_end
        )  ## CONNECTION WITH API

        message = "Error, no selected analysis. The returned data is the real data for the period."
        transformed_data = historical_data.copy()

        if selected_analysis == "S":
            transformation_config["get_season"] = True

            transformed_data = feature_engineering_pipeline(
            historical_data, transformation_config)
            
            season_period = transformed_data['avg_season'].iloc[1]
            transformed_data = transformed_data[['time', 'avg']]
            transformed_data['time'] = pd.to_datetime(transformed_data['time'])
            
            if season_period == None:
                message = "No seasonality was detected, the graph displays the real data for the period."
                
            else:
                message = "The detected seasonality period is of " + str(season_period) + " days. \n" + "The graph shows the approximated increments and decrements that occurs in the data due to the seasonal component."
              

        elif selected_analysis == "T":
            transformation_config["get_trend"] = True
            transformed_data = feature_engineering_pipeline(
            historical_data, transformation_config)
            transformed_data = transformed_data[['time', 'avg']].dropna()
            transformed_data['time'] = pd.to_datetime(transformed_data['time'])


            trend_delta = transformed_data['avg'].iloc[-1] - transformed_data['avg'].iloc[0]
            days = (transformed_data['time'].iloc[-1] - transformed_data['time'].iloc[0]).days
            trend_rate = trend_delta / days
            rounded_value = np.format_float_positional(trend_rate, precision=10, trim='-')  # Remove trailing zeros
            trend_rate = float(rounded_value[:rounded_value.rfind('0') + 3])
            message = "The trend rate from the extracted trend is of " + str(trend_rate) + " (units/day)."
            
            
            

        json_transformed_data = transformed_data.to_json(orient="records")
        data_list = json.loads(json_transformed_data)
        payload = {
        "message": message,    # e.g. "no trend detected"
        "data": data_list
        }

        payload_str = json.dumps(payload)


        #return payload_str
        return message , transformed_data
