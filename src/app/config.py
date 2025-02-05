import os
from notification.mail_sender import MailSender

PROJECT_FOLDER = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

STORE_DATA_PATH = os.path.join(PROJECT_FOLDER, os.path.join("data", "store.json"))

NEW_DATAPOINT_PATH = os.path.join(
    PROJECT_FOLDER, os.path.join("data", "new_datapoint.json")
)

CLEANED_PREDICTED_DATA_PATH = os.path.join(
    PROJECT_FOLDER, os.path.join("data", "cleaned_predicted_dataset.json")
)

ORIGINAL_ADAPTED_DATA_PATH = os.path.join(
    PROJECT_FOLDER, os.path.join("data", "original_adapted_dataset.json")
)

HISTORICAL_DATA_PATH = os.path.join(
    PROJECT_FOLDER, os.path.join("data", "historical_dataset.json")
)

STORE_PKL = os.path.join(PROJECT_FOLDER, os.path.join("data", "store.pkl"))

FORECASTING_MODELS_PKL = os.path.join(PROJECT_FOLDER, os.path.join("data", "forecasting_models.pkl"))

ALERTS_CONFIGURATION_PATH = os.path.join(PROJECT_FOLDER, os.path.join("data", "alerts_configuration.json"))

sender_email = "smartdashboard.teamb@libero.it"
sender_password = "SmartApp24-25"
recipient_email = "aura.natale7@gmail.com"

MAILER = MailSender(mail=sender_email, password=sender_password, recipient=recipient_email)
