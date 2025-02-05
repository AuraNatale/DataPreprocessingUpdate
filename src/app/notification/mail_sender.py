from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib


class MailSender:
    """
    A class to send emails using the SMTP protocol.
    At creation time it asks for the email, password and recipient's email.
    This because all this informations cannot be stored in the class, for security reasons.
    Note: only works with Libero Mail.
    """
    def __init__(self, mail: str = None, password: str = None, recipient: str = None):
        """
        Initializes the MailSender object.
        If mail, password or recipient are None, the user will be asked to input them.
        Arguments:
            mail (str|None): the email address of the sender.
            password (str|None): the password of the sender.
            recipient (str|None): the email address of the recipient.
        """
        if mail is None:
            self.mail = input("Enter your email: ")
        else:
            self.mail = mail
        if self.mail.split("@")[1] != "libero.it":
            raise ValueError("Only Libero Mail is supported.")
        if password is None:
            self.password = input("Enter your password: ")
        else:
            self.password = password
        if recipient is None:
            self.recipient = input("Enter the recipient's email: ")
        else:
            self.recipient = recipient
        self.anomaly_sent = False
        self.broken_sent = False

    def send_mail(self, subject: str, body: str) -> bool:
        """
        Sends an email to the recipient.
        Args:
            subject (str): the subject of the email.
            body (str): the body of the email.
        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        if self.anomaly_sent and "anomaly" in body:
            print("Anomaly email already sent.")
            return False
        if self.broken_sent and "malfunctioning" in body:
            return False

        msg = MIMEMultipart()
        msg["From"] = self.mail
        msg["To"] = self.recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        success = False
        server = None  # Initialize server as None to avoid UnboundLocalError

        try:
            server = smtplib.SMTP("smtp.libero.it", 587)
            server.starttls()
            server.login(self.mail, self.password)
            server.sendmail(self.mail, self.recipient, msg.as_string())
            print("Email sent successfully!")
            success = True

            if "anomaly" in body:
                print("\nAnomaly email sent.")
                self.anomaly_sent = True
            elif "malfunctioning" in body:
                self.broken_sent = True
        except Exception as e:
            print(f"Error: {e}")
        finally:
            if server:  # Only quit if server was successfully initialized
                server.quit()

        return success
