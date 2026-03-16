from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCharFormat,QColor,QTextCursor
import difflib

class DiffViewer(QTextEdit):

    def __init__(self):

        super().__init__()

        self.setReadOnly(True)

    def display(self, left, right, side="left"):

        self.clear()
        cursor = self.textCursor()

        sm = difflib.SequenceMatcher(None, left, right)

        for op, a1, a2, b1, b2 in sm.get_opcodes():

            if op == "equal":

                fmt = QTextCharFormat()
                cursor.insertText(left[a1:a2], fmt)

            elif op == "delete":

                if side == "left":
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor("red"))
                    cursor.insertText(left[a1:a2], fmt)

            elif op == "insert":

                if side == "right":
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor("green"))
                    cursor.insertText(right[b1:b2], fmt)

            elif op == "replace":

                if side == "left":
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor("red"))
                    cursor.insertText(left[a1:a2], fmt)

                if side == "right":
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor("green"))
                    cursor.insertText(right[b1:b2], fmt)