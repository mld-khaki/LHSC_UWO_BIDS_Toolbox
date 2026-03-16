from PySide6.QtWidgets import (
QMainWindow,
QWidget,
QVBoxLayout,
QHBoxLayout,
QPushButton,
QLabel
)

from natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.gui.diff_viewer import DiffViewer

class MainWindow(QMainWindow):

    def __init__(self,controller):

        super().__init__()

        self.controller = controller

        self.setWindowTitle("Diff Review Tool")

        layout = QVBoxLayout()

        self.status = QLabel()

        layout.addWidget(self.status)

        views = QHBoxLayout()

        self.left = DiffViewer()
        self.right = DiffViewer()

        views.addWidget(self.left)
        views.addWidget(self.right)

        layout.addLayout(views)

        buttons = QHBoxLayout()

        self.accept = QPushButton("Accept")
        self.discard = QPushButton("Discard")
        self.prev = QPushButton("Previous")
        self.skip = QPushButton("Skip")
        self.save = QPushButton("Save")
        self.quit = QPushButton("Quit")

        for b in [self.accept,self.discard,self.prev,self.skip,self.save,self.quit]:

            buttons.addWidget(b)

        layout.addLayout(buttons)

        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)

        self.accept.clicked.connect(controller.accept)
        self.discard.clicked.connect(controller.discard)
        self.prev.clicked.connect(controller.previous)
        self.skip.clicked.connect(controller.skip_file)
        self.save.clicked.connect(controller.save)
        self.quit.clicked.connect(controller.quit)