"""Builds the configured DentalPMSClient from environment. The only place
in this service that knows which transport (MySQL vs. the future REST API)
is active for the running clinic — everything else depends on the
DentalPMSClient interface, not a concrete class."""

import os

from ve_connect_dental.client import DentalPMSClient, OpenDentalAPIClient, OpenDentalMySQLClient


def build_client() -> DentalPMSClient:
    transport = os.getenv("OPENDENTAL_TRANSPORT", "mysql").lower()
    if transport == "mysql":
        return OpenDentalMySQLClient(
            host=os.getenv("OPENDENTAL_DB_HOST", "localhost"),
            port=int(os.getenv("OPENDENTAL_DB_PORT", 3306)),
            database=os.getenv("OPENDENTAL_DB_NAME", "opendental"),
            user=os.getenv("OPENDENTAL_DB_USER", "opendental"),
            password=os.getenv("OPENDENTAL_DB_PASSWORD", ""),
        )
    if transport == "api":
        return OpenDentalAPIClient(
            base_url=os.getenv("OPENDENTAL_API_BASE", ""),
            developer_key=os.getenv("OPENDENTAL_DEVELOPER_KEY", ""),
            customer_key=os.getenv("OPENDENTAL_CUSTOMER_KEY", ""),
        )
    raise ValueError(f"Unknown OPENDENTAL_TRANSPORT: {transport!r} (expected 'mysql' or 'api')")
