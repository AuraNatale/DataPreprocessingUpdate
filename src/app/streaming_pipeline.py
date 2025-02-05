from dataprocessing_functions import cleaning_pipeline, features, ad_predict, ad_train,ADWIN_drift,tdnn_forecasting_training,get_model_ad, get_model_ad_exp, update_model_forecast, update_model_ad, identity, ad_exp_train, update_model_ad_exp, ad_exp_predict, check_custom_alerts
from connection_functions import get_datapoint, get_historical_data, get_historical_data_mock, send_alert, store_datapoint

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import threading


# ----------------------------------------------
# Define a function to handle retraining in a different thread
# ----------------------------------------------
def retrain_models_after_drift(cleaned_datapoint):
    """
    This function retrieves historical data and retrains:
      - Anomaly detection
      - LIME explainer
      - Forecasting models
    """
    print("[TRAINING THREAD] Detected DRIFT. Retraining models...")

    # Call database to get historical data
    historical_data = get_historical_data_mock(
        cleaned_datapoint['name'],
        cleaned_datapoint['asset_id'],
        cleaned_datapoint['kpi'],
        cleaned_datapoint['operation'],
        "",
        cleaned_datapoint['time']
    )

    # 2) Retrain anomaly detection model
    model = ad_train(historical_data)
    update_model_ad(cleaned_datapoint, model)

    # 3) Retrain LIME explainer
    explainer = ad_exp_train(historical_data)
    update_model_ad_exp(cleaned_datapoint, explainer)

    # 4) Retrain forecasting models for each feature
    models = {}
    for feature_name in features:
        if feature_name in historical_data.columns:
            feature_df = historical_data[['time', feature_name]]
            # Ensure there's valid data for training
            if not (feature_df[feature_name].empty
                    or feature_df[feature_name].isna().all()
                    or feature_df[feature_name].isnull().all()):
                model_info = tdnn_forecasting_training(feature_df)
                models[feature_name] = model_info

    update_model_forecast(cleaned_datapoint, models)

    print("[TRAINING THREAD] Training completed.")


# ----------------------------------------------
# Main loop
# ----------------------------------------------
c = 0
from_drift = 0
check_drift = True

while c < 100:
    new_datapoint = get_datapoint(c)  # CONNECTION WITH API
    print(f"\n{new_datapoint}")

    cleaned_datapoint = cleaning_pipeline(new_datapoint)

    if cleaned_datapoint:
        # we now check if some drift has been detected
        if check_drift:
            drift_flag = ADWIN_drift(cleaned_datapoint)

            # we call the database to extract historical data

            if drift_flag:
                #start the thread for retraining models
                t = threading.Thread(target=retrain_models_after_drift, args=(cleaned_datapoint,))
                t.start()

                check_drift = False

        if not check_drift:
            from_drift += 1
            if from_drift > 7:
                from_drift = 0
                check_drift = True
                print('I can check the drift again')

        ad_model = get_model_ad(cleaned_datapoint)
        cleaned_datapoint['status'], anomaly_score = ad_predict(cleaned_datapoint, ad_model)

        if cleaned_datapoint['status'] == "Anomaly":
            anomaly_identity = {key: cleaned_datapoint[key] for key in identity if key in cleaned_datapoint}
            ad_exp_model = get_model_ad_exp(cleaned_datapoint)
            explanation = ad_exp_predict(cleaned_datapoint, ad_exp_model, ad_model)
            anomaly_identity['explanation'] = explanation
            send_alert(anomaly_identity, 'Anomaly', None, anomaly_score)

        #Check for customed alerts
        crossed_thresholds = check_custom_alerts(cleaned_datapoint)
        if crossed_thresholds is not None:

            customed_alert_identity = {key: cleaned_datapoint[key] for key in identity if key in cleaned_datapoint}

            customed_alert_identity['explanation'] = "The customed alert was triggered because the machine has \
            produced values " + crossed_thresholds['type'] + " threshold set by the user (being it = " + \
                str(crossed_thresholds["threshold_value"]) + ") for " + str(crossed_thresholds["days_counted"]) + " consecutive days."
            
            if crossed_thresholds["days_tolerance"] is not None:

                customed_alert_identity['explanation'] += "The tolerance for days " + crossed_thresholds['type'] + " was of "+\
                str(crossed_thresholds["days_tolerance"]) + " consecutive days."
                
            send_alert(customed_alert_identity, 'Customed Alert', None, None)
            

    store_datapoint(cleaned_datapoint)  # CONNECTION WITH API
    c += 1
