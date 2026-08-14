from dataclasses import dataclass
from datetime import datetime


@dataclass
class CertificateInfo:

    subject: str = ""
    issuer: str = ""
    serial: str = ""
    thumbprint: str = ""

    valid_from: datetime | None = None
    valid_to: datetime | None = None

    is_a3: bool = False
    is_cloud: bool = False

    provider: str = ""