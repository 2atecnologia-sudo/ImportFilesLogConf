def load_style():

    return """

    QWidget
    {
        background-color: #FFFFFF;
        color: #505050;
        font-size: 10pt;
        font-family: Segoe UI;
    }

    QMainWindow
    {
        background-color: white;
    }

    QLabel
    {
        color: #404040;
        background: transparent;
    }

    QGroupBox
    {
        font-weight: bold;
        border: 1px solid #D8D8D8;
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 10px;
        background-color: #FCFCFC;
    }

    QGroupBox::title
    {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0px 6px;
        color: #404040;
    }

    QLineEdit
    {
        background: white;
        border: 1px solid #C8C8C8;
        border-radius: 5px;
        padding: 5px;
        color: #404040;
    }

    QTextEdit
    {
        background: white;
        border: 1px solid #C8C8C8;
        border-radius: 5px;
        color: #404040;
    }

    QSpinBox
    {
        background: white;
        border: 1px solid #C8C8C8;
        border-radius: 5px;
        padding: 4px;
    }

    QPushButton
    {
        background-color: #1976D2;
        color: white;
        border-radius: 6px;
        border: none;
        padding: 7px 14px;
        font-weight: bold;
    }

    QPushButton:hover
    {
        background-color: #1565C0;
    }

    QPushButton:pressed
    {
        background-color: #0D47A1;
    }

    QStatusBar
    {
        background: #F3F3F3;
        color: #404040;
    }

    """