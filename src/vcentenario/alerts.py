from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from typing import List

from .config import (
    ALERT_EMAIL_ENABLED,
    ALERT_EMAIL_PASSWORD,
    ALERT_EMAIL_RECIPIENTS,
    ALERT_EMAIL_SMTP_PORT,
    ALERT_EMAIL_SMTP_SERVER,
    ALERT_EMAIL_USER,
    ALERT_INCIDENT_SEVERITY_THRESHOLD,
    ALERT_TRAFFIC_SCORE_THRESHOLD,
)

logger = logging.getLogger(__name__)


class AlertSystem:
    def __init__(self):
        self.enabled = ALERT_EMAIL_ENABLED

    def send_alert(self, subject: str, message: str) -> None:
        if not self.enabled:
            logger.debug("Alert system disabled, skipping alert: %s", subject)
            return

        if not ALERT_EMAIL_RECIPIENTS:
            logger.warning("No alert recipients configured")
            return

        try:
            msg = MIMEText(message)
            msg['Subject'] = subject
            msg['From'] = ALERT_EMAIL_USER
            msg['To'] = ", ".join(ALERT_EMAIL_RECIPIENTS)

            server = smtplib.SMTP(ALERT_EMAIL_SMTP_SERVER, ALERT_EMAIL_SMTP_PORT)
            server.starttls()
            server.login(ALERT_EMAIL_USER, ALERT_EMAIL_PASSWORD)
            server.sendmail(ALERT_EMAIL_USER, ALERT_EMAIL_RECIPIENTS, msg.as_string())
            server.quit()
            logger.info("Alert sent: %s", subject)
        except Exception as e:
            logger.error("Failed to send alert: %s", e)


def check_and_alert(state, incidents, alert_system: AlertSystem) -> None:
    alerts = []

    # Alert on high traffic score
    if state.traffic_score > ALERT_TRAFFIC_SCORE_THRESHOLD:
        alerts.append(f"Alto puntaje de tráfico: {state.traffic_score} ({state.traffic_level})")

    # Alert on severe incidents
    severe_incidents = [inc for inc in incidents if (inc.severity or "").lower() == ALERT_INCIDENT_SEVERITY_THRESHOLD.lower()]
    if severe_incidents:
        alerts.append(f"Incidentes severos: {len(severe_incidents)} (ej. {severe_incidents[0].incident_type})")

    if alerts:
        subject = "Alerta Puente V Centenario"
        message = "\n".join(alerts)
        alert_system.send_alert(subject, message)