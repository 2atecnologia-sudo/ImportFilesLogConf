class ApplicationController:

    def __init__(self):

        self.config = ConfigController()

        self.licence = LicenceController()

        self.certificate = CertificateController()

        self.worker = Worker()